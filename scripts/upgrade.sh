#!/usr/bin/env bash
set -euo pipefail

# NGFW Monitor 升级脚本

INSTALL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$INSTALL_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

echo "============================================"
echo "  NGFW Monitor 升级"
echo "============================================"
echo ""

# 检查当前是否在运行
if ! docker compose ps --quiet 2>/dev/null | grep -q .; then
    error "服务未运行，请先执行 install.sh"
fi

# 备份数据库
info "备份数据库..."
BACKUP_FILE="$INSTALL_DIR/backups/db_$(date +%Y%m%d_%H%M%S).sql.gz"
mkdir -p "$INSTALL_DIR/backups"
docker compose exec -T db pg_dump -U "${POSTGRES_USER:-ngfw}" "${POSTGRES_DB:-ngfw_monitor}" | gzip > "$BACKUP_FILE"
info "备份已保存: $BACKUP_FILE"

# 拉取新代码（如果是 git 仓库）
if [ -d "$INSTALL_DIR/.git" ]; then
    info "拉取最新代码..."
    git -C "$INSTALL_DIR" pull --ff-only || warn "Git pull 失败，使用本地代码继续"
fi

# 选择 compose 配置
COMPOSE_CMD="docker compose"
TOTAL_MEM_KB=$(grep MemTotal /proc/meminfo 2>/dev/null | awk '{print $2}' || echo "0")
if [ "$TOTAL_MEM_KB" -gt 8000000 ] && [ -f "$INSTALL_DIR/docker-compose.server.yml" ]; then
    COMPOSE_CMD="docker compose -f docker-compose.yml -f docker-compose.server.yml"
fi

# 重建镜像
info "重建镜像..."
$COMPOSE_CMD build --quiet

# 报表卷属主修正：容器改为以 uid 1000 运行后，早先由 root 建出来的
# reportdata 卷变成只读，报表生成会失败。幂等，属主已对时是空操作。
info "修正报表目录属主..."
$COMPOSE_CMD run --rm --no-deps --user root --entrypoint sh backend \
    -c 'chown -R 1000:1000 /app/data' >/dev/null 2>&1 \
    || warn "报表目录属主修正失败，若报表生成报 Permission denied 请手动执行"

# 滚动重启（先启动新容器再停旧的，减少停机时间）
info "重启服务..."
$COMPOSE_CMD up -d --remove-orphans

# 等待健康
info "等待服务就绪..."
for i in $(seq 1 30); do
    if docker compose ps 2>/dev/null | grep -q "(healthy)"; then
        break
    fi
    sleep 2
done

# 运行数据库迁移（如果有 alembic）
if [ -f "$INSTALL_DIR/backend/alembic.ini" ]; then
    info "执行数据库迁移..."
    $COMPOSE_CMD exec -T backend alembic upgrade head 2>/dev/null || warn "迁移命令跳过（可能无新迁移）"
fi

echo ""
info "升级完成！"
echo ""
echo "  如需回滚数据库: gunzip < $BACKUP_FILE | docker compose exec -T db psql -U ngfw ngfw_monitor"
echo ""
