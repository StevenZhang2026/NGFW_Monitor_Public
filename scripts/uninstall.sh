#!/usr/bin/env bash
set -euo pipefail

# NGFW Monitor 卸载脚本

INSTALL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$INSTALL_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }

echo "============================================"
echo "  NGFW Monitor 卸载"
echo "============================================"
echo ""

read -rp "确认卸载 NGFW Monitor？数据库数据将被清除。[y/N]: " CONFIRM
if [[ ! "$CONFIRM" =~ ^[yY]$ ]]; then
    echo "已取消。"
    exit 0
fi

# 可选导出数据
read -rp "卸载前导出数据库备份？[Y/n]: " BACKUP
if [[ ! "$BACKUP" =~ ^[nN]$ ]]; then
    BACKUP_FILE="$INSTALL_DIR/backups/db_final_$(date +%Y%m%d_%H%M%S).sql.gz"
    mkdir -p "$INSTALL_DIR/backups"
    docker compose exec -T db pg_dump -U "${POSTGRES_USER:-ngfw}" "${POSTGRES_DB:-ngfw_monitor}" 2>/dev/null | gzip > "$BACKUP_FILE" && \
        info "备份已保存: $BACKUP_FILE" || \
        warn "备份失败（数据库可能未运行）"
fi

info "停止并删除容器..."
docker compose down -v --remove-orphans 2>/dev/null || true

info "清理 Docker 镜像..."
docker compose config --images 2>/dev/null | xargs -r docker rmi 2>/dev/null || true

echo ""
info "卸载完成。"
echo ""
echo "  以下文件保留（需手动删除）:"
echo "    - 配置文件: $INSTALL_DIR/.env"
echo "    - 证书文件: $INSTALL_DIR/certs/"
echo "    - 数据备份: $INSTALL_DIR/backups/"
echo "    - 项目代码: $INSTALL_DIR/"
echo ""
echo "  完全清除: rm -rf $INSTALL_DIR"
echo ""
