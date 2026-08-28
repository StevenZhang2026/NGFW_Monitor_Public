#!/usr/bin/env bash
# pre-commit / pre-push 共用的 gitleaks 调用。被两个 hook source，本身不是 hook。
#
# 这个目录靠 core.hooksPath 生效（跑 scripts/install-git-hooks.sh 设置）。hook 本体
# 进版本控制，所以逻辑改动会出现在 diff 里，而不是躲在每台机器各自的 .git/hooks 里。
#
# 规则见 .gitleaks.toml（默认规则集 + PAN-OS API Key + URL 里的明文密码
# + *.example 里的真值）。
# 绕过单次检查：git commit --no-verify / git push --no-verify

GITLEAKS_IMAGE="zricethezav/gitleaks:v8.30.1"

# 优先用本机 gitleaks，没有就起一次性容器。
run_gitleaks() {
    local repo_root
    repo_root=$(git rev-parse --show-toplevel)
    if command -v gitleaks >/dev/null 2>&1; then
        gitleaks "$@" --config "$repo_root/.gitleaks.toml" --no-banner --redact
    elif command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
        # 容器里 git 是 root，宿主目录属主不同会报 dubious ownership，故设 safe.directory
        docker run --rm -v "$repo_root:/src:ro" -w /src \
            -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0=/src \
            "$GITLEAKS_IMAGE" "$@" --config /src/.gitleaks.toml --no-banner --redact
    else
        echo "[gitleaks] 跳过：本机没有 gitleaks 也没有可用的 docker" >&2
        echo "[gitleaks] 安装其一：brew install gitleaks   或启动 Docker Desktop" >&2
        return 0
    fi
}
