#!/usr/bin/env bash
# 安装 gitleaks 凭据门禁（pre-commit + pre-push）。
# .git/hooks 不进版本控制，所以每台机器 clone 后跑一次：
#   bash scripts/install-git-hooks.sh
#
# 规则见 .gitleaks.toml（默认规则集 + PAN-OS API Key + URL 里的明文密码
# + *.example 里的真值）。
# 绕过单次检查：git commit --no-verify / git push --no-verify
set -euo pipefail

REPO_ROOT=$(git rev-parse --show-toplevel)
HOOKS_DIR="$REPO_ROOT/.git/hooks"
GITLEAKS_IMAGE="zricethezav/gitleaks:v8.30.1"

# 两个 hook 共用的调用逻辑：优先用本机 gitleaks，没有就起一次性容器。
RUNNER=$(cat <<'RUNNER_EOF'
run_gitleaks() {
    local repo_root
    repo_root=$(git rev-parse --show-toplevel)
    if command -v gitleaks >/dev/null 2>&1; then
        gitleaks "$@" --config "$repo_root/.gitleaks.toml" --no-banner --redact
    elif command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
        # 容器里 git 是 root，宿主目录属主不同会报 dubious ownership，故设 safe.directory
        docker run --rm -v "$repo_root:/src:ro" -w /src \
            -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0=/src \
            GITLEAKS_IMAGE_PLACEHOLDER "$@" --config /src/.gitleaks.toml --no-banner --redact
    else
        echo "[gitleaks] 跳过：本机没有 gitleaks 也没有可用的 docker" >&2
        echo "[gitleaks] 安装其一：brew install gitleaks   或启动 Docker Desktop" >&2
        return 0
    fi
}
RUNNER_EOF
)
RUNNER=${RUNNER//GITLEAKS_IMAGE_PLACEHOLDER/$GITLEAKS_IMAGE}

# ---- pre-commit：只扫暂存区，凭据在进 commit 之前就被挡住 ----
cat > "$HOOKS_DIR/pre-commit" <<EOF
#!/usr/bin/env bash
# 由 scripts/install-git-hooks.sh 生成
set -uo pipefail

$RUNNER

if ! run_gitleaks git --staged /src; then
    echo "" >&2
    echo "[gitleaks] 暂存区里有凭据，提交已阻止。" >&2
    echo "  改掉真值后重新 git add；确认是误报再用 git commit --no-verify" >&2
    exit 1
fi
EOF

# ---- pre-push：扫所有还没推到任何 remote 的 commit ----
# 用 --not --remotes 而不是全量历史：仓库历史里已经有过泄露（见 CHANGELOG/
# 安全基线记录），全量扫会永远红着，门禁就形同虚设。
cat > "$HOOKS_DIR/pre-push" <<EOF
#!/usr/bin/env bash
# 由 scripts/install-git-hooks.sh 生成
set -uo pipefail

$RUNNER

if ! run_gitleaks git /src --log-opts="--all --not --remotes"; then
    echo "" >&2
    echo "[gitleaks] 待推送的 commit 里有凭据，push 已阻止。" >&2
    echo "  这些 commit 还没上远端，现在还能改历史：" >&2
    echo "    git rebase -i <base>   或   git reset --soft <base> 后重新提交" >&2
    echo "  已经推上去的凭据只能靠轮换，删文件没用。" >&2
    exit 1
fi
EOF

chmod +x "$HOOKS_DIR/pre-commit" "$HOOKS_DIR/pre-push"
echo "已安装: .git/hooks/pre-commit, .git/hooks/pre-push"
echo "自检:   bash scripts/install-git-hooks.sh 后随便 git add 一个含密码的文件试试"
