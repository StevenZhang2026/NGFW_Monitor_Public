#!/usr/bin/env bash
set -euo pipefail

# NGFW Monitor 安装脚本
# 适用于 Ubuntu 20.04+ / CentOS 8+ / Debian 11+

INSTALL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$INSTALL_DIR/.env"
COMPOSE_FILE="$INSTALL_DIR/docker-compose.yml"
CERTS_DIR="$INSTALL_DIR/certs"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

echo "============================================"
echo "  NGFW Monitor 安装程序"
echo "  Palo Alto 防火墙集中监控平台"
echo "============================================"
echo ""

# ---- 1. 检查依赖 ----
info "检查系统依赖..."

if ! command -v docker &>/dev/null; then
    error "未安装 Docker。请先安装: https://docs.docker.com/engine/install/"
fi

if ! docker compose version &>/dev/null 2>&1; then
    if ! docker-compose --version &>/dev/null 2>&1; then
        error "未安装 Docker Compose。请安装 Docker Compose V2。"
    fi
fi

if ! docker info &>/dev/null 2>&1; then
    error "Docker 未运行或当前用户无权限。请确认 Docker 服务已启动且用户在 docker 组中。"
fi

info "Docker $(docker --version | grep -oP '\d+\.\d+\.\d+') ✓"

# ---- 2. 生成 .env ----
if [ -f "$ENV_FILE" ]; then
    warn ".env 已存在，跳过生成（如需重新配置请删除 .env 后重新运行）"
else
    info "生成配置文件..."

    # 生成随机密码和密钥
    DB_PASSWORD=$(openssl rand -base64 24 | tr -dc 'a-zA-Z0-9' | head -c 24)
    SECRET_KEY=$(openssl rand -hex 32)
    JWT_SECRET_KEY=$(openssl rand -hex 32)

    read -rp "  Web 访问端口 [默认 443]: " WEB_PORT
    WEB_PORT=${WEB_PORT:-443}

    read -rp "  管理员初始密码 [默认自动生成]: " ADMIN_PASSWORD
    if [ -z "$ADMIN_PASSWORD" ]; then
        ADMIN_PASSWORD=$(openssl rand -base64 16 | tr -dc 'a-zA-Z0-9!@#$%' | head -c 16)
        info "管理员密码已生成: $ADMIN_PASSWORD （请妥善保存）"
    fi

    cat > "$ENV_FILE" << EOF
# NGFW Monitor 配置 - 由 install.sh 自动生成于 $(date +%Y-%m-%d)
# 修改后执行: docker compose up -d 生效

# 数据库
POSTGRES_DB=ngfw_monitor
POSTGRES_USER=ngfw
POSTGRES_PASSWORD=${DB_PASSWORD}
DATABASE_URL=postgresql+asyncpg://ngfw:${DB_PASSWORD}@db:5432/ngfw_monitor

# Redis
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1

# 安全（变量名必须与 backend/app/config.py 的 Settings 字段一致，否则会静默回落到 "change-me"）
SECRET_KEY=${SECRET_KEY}
JWT_SECRET_KEY=${JWT_SECRET_KEY}
ADMIN_USERNAME=admin
ADMIN_PASSWORD=${ADMIN_PASSWORD}

# Web
WEB_PORT=${WEB_PORT}
CORS_ORIGINS=["https://localhost:${WEB_PORT}"]
EOF

    chmod 600 "$ENV_FILE"
    info ".env 已生成 (权限 600)"
fi

# ---- 3. 生成自签名证书 ----
if [ -f "$CERTS_DIR/server.crt" ] && [ -f "$CERTS_DIR/server.key" ]; then
    warn "TLS 证书已存在，跳过生成"
else
    info "生成自签名 TLS 证书..."
    mkdir -p "$CERTS_DIR"

    read -rp "  服务器域名/IP [默认 localhost]: " SERVER_HOST
    SERVER_HOST=${SERVER_HOST:-localhost}

    openssl req -x509 -nodes -days 3650 \
        -newkey rsa:2048 \
        -keyout "$CERTS_DIR/server.key" \
        -out "$CERTS_DIR/server.crt" \
        -subj "/CN=${SERVER_HOST}" \
        -addext "subjectAltName=DNS:${SERVER_HOST},IP:127.0.0.1" \
        2>/dev/null

    chmod 600 "$CERTS_DIR/server.key"
    info "证书已生成 (有效期 10 年)"
fi

# ---- 4. 构建并启动 ----
info "构建 Docker 镜像（首次约 3-5 分钟）..."
cd "$INSTALL_DIR"

# 如果有 server overlay 且系统内存 >= 8G，使用 server 配置
COMPOSE_CMD="docker compose"
TOTAL_MEM_KB=$(grep MemTotal /proc/meminfo 2>/dev/null | awk '{print $2}' || echo "0")
if [ "$TOTAL_MEM_KB" -gt 8000000 ] && [ -f "$INSTALL_DIR/docker-compose.server.yml" ]; then
    COMPOSE_CMD="docker compose -f docker-compose.yml -f docker-compose.server.yml"
    info "检测到 8G+ 内存，启用服务器配置（多 worker 副本）"
fi

$COMPOSE_CMD build --quiet
info "镜像构建完成"

info "启动服务..."
$COMPOSE_CMD up -d

# ---- 5. 等待健康检查 ----
info "等待服务就绪..."
for i in $(seq 1 30); do
    if docker compose ps --format json 2>/dev/null | grep -q '"Health":"healthy"' || \
       docker compose ps 2>/dev/null | grep -q "(healthy)"; then
        break
    fi
    sleep 2
done

# ---- 6. 初始化数据库 ----
info "初始化数据库..."
$COMPOSE_CMD exec -T backend python -c "
import asyncio
from app.main import app
from app.database import engine, Base
async def init():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
asyncio.run(init())
" 2>/dev/null || warn "数据库初始化命令执行失败（可能已初始化）"

# ---- 7. 完成 ----
echo ""
echo "============================================"
info "安装完成！"
echo ""
echo "  访问地址:  https://$(hostname -I 2>/dev/null | awk '{print $1}' || echo 'localhost'):${WEB_PORT:-443}"
echo "  默认账号:  admin"
echo "  默认密码:  查看 .env 中的 ADMIN_PASSWORD"
echo ""
echo "  常用命令:"
echo "    查看状态:  docker compose ps"
echo "    查看日志:  docker compose logs -f worker"
echo "    停止服务:  docker compose stop"
echo "    重启服务:  docker compose restart"
echo "    升级版本:  bash scripts/upgrade.sh"
echo "    卸载:      bash scripts/uninstall.sh"
echo "============================================"
