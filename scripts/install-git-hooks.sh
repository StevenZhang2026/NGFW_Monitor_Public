#!/usr/bin/env bash
# 让 git 用仓库里的 scripts/githooks 当 hook 目录。每台机器 clone 后跑一次：
#   bash scripts/install-git-hooks.sh
#
# 为什么还需要这一步：git 不允许仓库自带的 hook 自动生效（否则 clone 就等于执行任意
# 代码），core.hooksPath 只能写进本地 .git/config。但 hook 本体已经进版本控制了，
# 不再由这个脚本生成 —— 要改门禁逻辑就直接改 scripts/githooks/ 下的文件。
set -euo pipefail

REPO_ROOT=$(git rev-parse --show-toplevel)
HOOKS_DIR=scripts/githooks   # 相对仓库根，换机器换路径都不用改
cd "$REPO_ROOT"

chmod +x "$HOOKS_DIR/pre-commit" "$HOOKS_DIR/pre-push"
git config core.hooksPath "$HOOKS_DIR"

# 旧版本把 hook 生成到 .git/hooks。设了 hooksPath 之后 git 不再看那个目录，留着只会
# 让人误以为改那份文件有用。只删本脚本自己生成的（带生成标记），手写的不动。
for old in .git/hooks/pre-commit .git/hooks/pre-push; do
    if [ -f "$old" ] && grep -q "由 scripts/install-git-hooks.sh 生成" "$old"; then
        rm -f "$old"
        echo "已清理旧的生成产物: $old"
    fi
done

# 变量名后面紧跟全角括号必须用 ${}：bash 会把「（」的字节当成标识符的一部分，
# 于是 $HOOKS_DIR（…） 展开成 unbound variable，set -e 直接让脚本退出。
echo "已设置 core.hooksPath = ${HOOKS_DIR}（pre-commit 挡凭据；pre-push 挡凭据 + 跑安全关卡 + 提醒 fix 补测试）"
echo "自检:   随便 git add 一个含密码的文件试试，应该被挡住"
