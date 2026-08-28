#!/usr/bin/env bash
# 后端测试。
#
#   bash scripts/test-backend.sh            跑全部
#   bash scripts/test-backend.sh -k parser  透传参数给 pytest
#
# 为什么绕一圈 Docker：宿主机只有系统自带的 Python 3.9，项目要 3.11+，而且 lxml /
# asyncpg 这些都没装。backend 镜像里全都有，所以用一次性容器跑。
#
# 为什么挂 -v 而不是直接 exec 到跑着的 backend 容器：compose 里 backend 没有源码
# bind mount（代码是打进镜像的），不挂载就得每次改完测试都重建镜像。
#
# 为什么 python -m pytest 而不是 pytest：容器里是非 root 用户，pip --user 装到
# ~/.local/bin，不在 PATH 上。
#
# 为什么 --no-deps：第一批测试全是纯函数，不需要 db / redis。等有了要真 Postgres 的
# 集成测试，这里去掉 --no-deps。
set -euo pipefail

cd "$(dirname "$0")/.."

exec docker compose run --rm --no-deps \
  -v "$PWD/backend:/app" -w /app backend \
  sh -c "pip install -q -r requirements-dev.txt && python -m pytest -q $*"
