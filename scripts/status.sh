#!/usr/bin/env bash
set -euo pipefail

# NGFW Monitor 状态检查

INSTALL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$INSTALL_DIR"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "============================================"
echo "  NGFW Monitor 状态"
echo "============================================"
echo ""

# 容器状态
echo "▸ 服务状态:"
docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || \
    docker compose ps 2>/dev/null || echo "  服务未运行"
echo ""

# 磁盘占用
echo "▸ 数据卷:"
docker system df --verbose 2>/dev/null | grep -A20 "VOLUME NAME" | head -10 || true
echo ""

# 数据库大小
DB_SIZE=$(docker compose exec -T db psql -U ngfw -d ngfw_monitor -t -c \
    "SELECT pg_size_pretty(pg_database_size('ngfw_monitor'));" 2>/dev/null | tr -d ' ')
if [ -n "$DB_SIZE" ]; then
    echo -e "▸ 数据库大小: ${GREEN}${DB_SIZE}${NC}"
fi

# 指标数据行数
ROW_COUNT=$(docker compose exec -T db psql -U ngfw -d ngfw_monitor -t -c \
    "SELECT to_char(count(*), 'FM999,999,999') FROM metric_data;" 2>/dev/null | tr -d ' ')
if [ -n "$ROW_COUNT" ]; then
    echo -e "▸ 指标数据:   ${GREEN}${ROW_COUNT} 条${NC}"
fi

# 设备数
DEVICE_COUNT=$(docker compose exec -T db psql -U ngfw -d ngfw_monitor -t -c \
    "SELECT count(*) FROM devices;" 2>/dev/null | tr -d ' ')
if [ -n "$DEVICE_COUNT" ]; then
    echo -e "▸ 已接入设备: ${GREEN}${DEVICE_COUNT} 台${NC}"
fi

echo ""

# 最近采集
echo "▸ 最近采集 (worker 日志):"
docker compose logs worker --tail 5 --no-log-prefix 2>/dev/null | tail -5 || echo "  无日志"
echo ""
