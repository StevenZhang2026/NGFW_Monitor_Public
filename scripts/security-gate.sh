#!/usr/bin/env bash
# 发布前安全关卡。确定性、不用 LLM、只报「相对 baseline 的新增」。
#
#   bash scripts/security-gate.sh                    检查，有新增则 exit 1
#   bash scripts/security-gate.sh --update-baseline   重新生成 baseline
#
# 为什么只报新增：仓库里有 30 条已人工判定为误报的 bandit 命中（17×B608 f-string SQL
# 全部可追溯到 int() 转换/字面量分支/白名单，10×B501 + 3×B507 是设备侧管理网自签名
# 证书的既定取舍），和 5 条历史凭据泄露（已全部轮换）。全量报警的关卡第一次就是红的，
# 两周内就会被 --no-verify 绕过或删掉。判定结论落在 security/*.json 里，关卡只看增量。
#
# 什么时候重新生成 baseline：修完真实问题后，或大规模重构导致 bandit 行号漂移后。
# **不要**用它来消掉"真的但暂时不修"的问题 —— 那种记进 docs/roadmap.md。
#
# 关卡覆盖不到的：授权缺陷、IDOR、业务逻辑、prompt 注入。那些要 /security-review
# （LLM，看 diff）或 /security-scan（LLM，全库 + 分诊）。关卡绿不等于代码安全。
#
# 环境变量：
#   SECURITY_GATE_CA_BUNDLE  企业根 CA 的 PEM 路径。只在开发机走了带 TLS 解密代理的
#                            公司网络时需要 —— 那时拉规则库 / 查 advisory 的容器会
#                            CERTIFICATE_VERIFY_FAILED。拦截是按域名的，可能只有
#                            semgrep 挂。macOS 上现生成一份：
#                              { security find-certificate -a -p \
#                                  /System/Library/Keychains/SystemRootCertificates.keychain
#                                security find-certificate -a -p \
#                                  /Library/Keychains/System.keychain; } > /tmp/gate-ca.pem
#   SKIP_NETWORK_SCANS=1     跳过需要联网的项（pip-audit / npm audit / semgrep）

set -uo pipefail

REPO=$(git rev-parse --show-toplevel)   # 绝对路径：cwd 会在调用间漂移，用 $PWD 会静默扫错目录
cd "$REPO"

BASELINE_DIR="$REPO/security"
GITLEAKS_IMAGE="zricethezav/gitleaks:v8.30.1"
MODE="check"
[ "${1:-}" = "--update-baseline" ] && MODE="update"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
pass() { echo -e "  ${GREEN}PASS${NC}  $1"; }
fail() { echo -e "  ${RED}FAIL${NC}  $1"; FAILED=$((FAILED + 1)); }
skip() { echo -e "  ${YELLOW}SKIP${NC}  $1"; }
FAILED=0

# 企业 CA：挂进每个容器，并设各工具各自认的那个变量名。
# 初值不能是空数组：macOS 自带 bash 3.2 下 set -u 遇到 "${CA_ARGS[@]}" 展开空数组
# 会报 unbound variable，于是"没连 GP"这条正常路径反而跑不起来。塞一个无害的 -e
# 让它永远非空。
CA_ARGS=(-e SECURITY_GATE=1)
if [ -n "${SECURITY_GATE_CA_BUNDLE:-}" ] && [ -f "${SECURITY_GATE_CA_BUNDLE}" ]; then
    CA_ARGS+=(-v "${SECURITY_GATE_CA_BUNDLE}:/ca.pem:ro"
              -e REQUESTS_CA_BUNDLE=/ca.pem -e SSL_CERT_FILE=/ca.pem
              -e PIP_CERT=/ca.pem -e CURL_CA_BUNDLE=/ca.pem)
fi

docker info >/dev/null 2>&1 || { echo "Docker 不可用，关卡无法运行"; exit 2; }
mkdir -p "$BASELINE_DIR"

echo "============================================"
echo "  安全关卡  ($MODE)"
echo "============================================"

# ---------- 1. 凭据（全历史） ----------
# pre-commit/pre-push 已经拦了新提交，这里补的是历史被改写（rebase/filter-branch）
# 或有人 --no-verify 绕过的情况。
echo ""
echo "[1/5] gitleaks —— 凭据（全 git 历史）"
GL_ARGS=(--rm -v "$REPO:/src:ro" -v "$BASELINE_DIR:/out" -w /src
         -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0=/src)
if [ "$MODE" = "update" ]; then
    docker run "${GL_ARGS[@]}" "$GITLEAKS_IMAGE" git /src \
        --config /src/.gitleaks.toml --report-path /out/gitleaks-baseline.json \
        -f json --no-banner --redact --exit-code 0 >/dev/null 2>&1
    pass "baseline 已写入 security/gitleaks-baseline.json（$(python3 -c "import json;print(len(json.load(open('$BASELINE_DIR/gitleaks-baseline.json'))))") 条）"
else
    # -v：不加的话 FAIL 时日志里只有一句 "leaks found: N"，看不到是哪一条
    if docker run "${GL_ARGS[@]}" "$GITLEAKS_IMAGE" git /src \
        --config /src/.gitleaks.toml --baseline-path /out/gitleaks-baseline.json \
        --no-banner --redact -v >/tmp/gate-gitleaks.log 2>&1; then
        pass "无新增凭据"
    else
        fail "发现 baseline 之外的凭据 —— 见 /tmp/gate-gitleaks.log"
        echo "        凭据一旦进历史，删文件没用，必须轮换。"
    fi
fi

# ---------- 2. Python SAST ----------
# 必须 install 和 run 在同一个 sh -c 里：分开的 install 容器会被丢掉。
# bandit 的 baseline 按 (文件, 行号, test_id) 匹配，重构后行号漂移会误报新增，
# 那时重新生成 baseline。挂载路径是 baseline 的一部分，改了就对不上。
echo ""
echo "[2/5] bandit —— Python SAST"
BD_RUN='pip install -q bandit >/dev/null 2>&1 && python -m bandit -r /src/app -ll'
if [ "$MODE" = "update" ]; then
    docker run --rm -v "$REPO/backend:/src:ro" -v "$BASELINE_DIR:/out" python:3.11-slim \
        sh -c "$BD_RUN -f json -o /out/bandit-baseline.json" >/dev/null 2>&1
    pass "baseline 已写入 security/bandit-baseline.json（$(python3 -c "import json;print(len(json.load(open('$BASELINE_DIR/bandit-baseline.json'))['results']))") 条）"
else
    if docker run --rm -v "$REPO/backend:/src:ro" -v "$BASELINE_DIR:/out" python:3.11-slim \
        sh -c "$BD_RUN -b /out/bandit-baseline.json -f txt" >/tmp/gate-bandit.log 2>&1; then
        pass "无新增 Python SAST 问题"
    else
        fail "发现 baseline 之外的问题 —— 见 /tmp/gate-bandit.log"
    fi
fi

# ---------- 3. 依赖 CVE / IaC / 密钥 ----------
# 阈值 HIGH,CRITICAL。MEDIUM 及以下的已知项（echarts XSS、react-router 开放重定向、
# vite/esbuild dev server）记在 docs/roadmap.md，不在这里拦。
# skip-dirs certs：本地自签名证书，.gitignore 里，从不进仓库也不进发布。
# db-repository 用 ghcr：默认的 mirror.gcr.io 会间歇性 unexpected EOF。
echo ""
echo "[3/5] trivy —— 依赖 CVE + 容器/IaC 配置 + 密钥"
if [ "$MODE" = "update" ]; then
    skip "trivy 用 .trivyignore（手工维护），无需生成"
else
    if docker run --rm -v "$REPO:/src:ro" -v trivy-cache:/root/.cache "${CA_ARGS[@]}" aquasec/trivy \
        fs --scanners vuln,secret,misconfig --severity HIGH,CRITICAL \
        --skip-dirs certs --ignorefile /src/.trivyignore \
        --db-repository ghcr.io/aquasecurity/trivy-db:2 --timeout 30m \
        --exit-code 1 --quiet /src >/tmp/gate-trivy.log 2>&1; then
        pass "无 HIGH/CRITICAL"
    else
        fail "发现 HIGH/CRITICAL —— 见 /tmp/gate-trivy.log"
    fi
fi

# ---------- 4. 语言无关 SAST ----------
# 只拦 ERROR 级：WARNING 及以下的误报率高到不适合做关卡。
# 用显式 ruleset 而不是 --config=auto —— auto 会把仓库元数据发给 semgrep registry。
# 单条误报就地用 `# nosemgrep: <rule-id>` 抑制并写理由，不进 baseline 文件。
echo ""
echo "[4/5] semgrep —— 语言无关 SAST（ERROR 级）"
if [ "$MODE" = "update" ]; then
    skip "semgrep 用就地 # nosemgrep 抑制，无 baseline 文件"
elif [ "${SKIP_NETWORK_SCANS:-0}" = "1" ]; then
    skip "SKIP_NETWORK_SCANS=1"
else
    # 退出码要分开看：semgrep 1=有命中，2=自己跑挂了（拉不到规则库最常见）。
    # 两者都当"发现问题"的话，日志空白却报 FAIL，排查方向完全错。
    docker run --rm -v "$REPO:/src:ro" "${CA_ARGS[@]}" semgrep/semgrep \
        semgrep scan --config=p/security-audit --config=p/secrets \
        --severity=ERROR --error --quiet /src >/tmp/gate-semgrep.log 2>&1
    case $? in
        0) pass "无 ERROR 级命中" ;;
        1) fail "发现 ERROR 级命中 —— 见 /tmp/gate-semgrep.log" ;;
        *) fail "semgrep 未能运行（不是代码问题）—— 见 /tmp/gate-semgrep.log"
           echo "        规则库要从 semgrep.dev 现拉，没有本地缓存。CERTIFICATE_VERIFY_FAILED"
           echo "        说明这个域被 TLS 解密代理拦了 —— 拦截是按域名的，同一次运行里"
           echo "        pypi/ghcr/npm 可能全都正常。设 SECURITY_GATE_CA_BUNDLE=<代理根CA.pem>，"
           echo "        或换网络。--quiet 会吞掉这类失败的输出，日志空白时去掉它重跑。" ;;
    esac
fi

# ---------- 5. 依赖 advisory ----------
# trivy 在某些布局下会跳过 Python requirements（Report Summary 里只列 package-lock.json），
# 所以 pip-audit 必须单独跑，不能假设 trivy 覆盖了。
# npm audit 打 registry.npmjs.org：镜像源（npmmirror/cnpm/Artifactory）会返回
# 404 [NOT_IMPLEMENTED] /-/npm/v1/security/*。
echo ""
echo "[5/5] pip-audit / npm audit —— 依赖 advisory"
if [ "$MODE" = "update" ]; then
    skip "用 --ignore-vuln / --audit-level 阈值，无 baseline 文件"
elif [ "${SKIP_NETWORK_SCANS:-0}" = "1" ]; then
    skip "SKIP_NETWORK_SCANS=1"
else
    # PYSEC-2026-1325 (ecdsa 侧信道)：无可用修复版本，且本项目 JWT 固定
    # algorithms=["HS256"]，ECDSA 代码路径不可达。
    if docker run --rm -v "$REPO/backend:/src:ro" "${CA_ARGS[@]}" python:3.11-slim \
        sh -c 'pip install -q pip-audit >/dev/null 2>&1 && pip-audit -r /src/requirements.txt --ignore-vuln PYSEC-2026-1325' \
        >/tmp/gate-pipaudit.log 2>&1; then
        pass "pip-audit 无新增"
    else
        fail "pip-audit 发现问题 —— 见 /tmp/gate-pipaudit.log"
    fi

    if docker run --rm -v "$REPO/frontend:/app" -w /app "${CA_ARGS[@]}" node:20-alpine \
        sh -c 'npm audit --audit-level=critical --registry=https://registry.npmjs.org' \
        >/tmp/gate-npmaudit.log 2>&1; then
        pass "npm audit 无 critical"
    else
        fail "npm audit 发现 critical —— 见 /tmp/gate-npmaudit.log"
    fi
fi

echo ""
echo "============================================"
if [ "$MODE" = "update" ]; then
    echo "baseline 已更新。请 review 后再提交 —— 这一步等于把当前所有已知问题"
    echo "标为「已接受」，提交记录是唯一的审计痕迹。"
    echo "  git diff --stat security/"
    exit 0
fi
if [ "$FAILED" -eq 0 ]; then
    echo -e "${GREEN}关卡通过${NC}（$FAILED 项失败）"
    echo "注意：关卡看不到授权缺陷、IDOR、业务逻辑漏洞、prompt 注入。"
    exit 0
fi
echo -e "${RED}关卡未通过：$FAILED 项失败${NC}"
echo "逐项判定新增命中是真问题还是误报。误报的处理方式："
echo "  bandit  -> 修完真问题后 bash scripts/security-gate.sh --update-baseline"
echo "  semgrep -> 就地加 # nosemgrep: <rule-id> 并写理由"
echo "  trivy   -> 加进 .trivyignore 并写理由"
echo "需要带分诊的深入分析时跑 /security-scan。"
exit 1
