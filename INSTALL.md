# NGFW Monitor 安装指南

## 系统要求

| 项目 | 最低 | 推荐 |
|------|------|------|
| OS | Ubuntu 20.04 / CentOS 8 / Debian 11 | Ubuntu 22.04 |
| CPU | 2 核 | 4 核 |
| 内存 | 4 GB | 8 GB+ |
| 磁盘 | 20 GB | 50 GB+（含历史数据） |
| Docker | 20.10+ | 最新稳定版 |
| Docker Compose | V2 | 最新 |

服务器需能通过网络访问防火墙管理口（HTTPS 443 + SSH 22）。

## 快速安装

```bash
# 1. 获取代码
git clone https://github.com/StevenZhang2026/NGFW_bytedance.git
cd NGFW_bytedance

# 2. 运行安装脚本
bash scripts/install.sh
```

安装脚本会：
- 检查 Docker 环境
- 交互式生成 `.env` 配置（数据库密码自动生成）
- 生成自签名 HTTPS 证书
- 构建并启动所有服务

安装完成后，浏览器访问 `https://<服务器IP>:443`。

## 手动安装

如果不使用安装脚本，按以下步骤操作：

```bash
# 1. 复制并编辑配置
cp .env.example .env
vim .env   # 修改 POSTGRES_PASSWORD、SECRET_KEY 等

# 2. 生成证书
mkdir -p certs
openssl req -x509 -nodes -days 3650 \
    -newkey rsa:2048 \
    -keyout certs/server.key \
    -out certs/server.crt \
    -subj "/CN=your-server-ip"

# 3. 构建并启动
docker compose build
docker compose up -d

# 4. 验证
docker compose ps   # 所有服务应为 healthy
```

## 日常运维

```bash
# 查看服务状态
bash scripts/status.sh

# 查看采集日志
docker compose logs worker --tail 50 -f

# 重启所有服务
docker compose restart

# 仅重启后端（代码更新后）
docker compose build backend worker beat
docker compose up -d backend worker beat
```

## 升级

```bash
bash scripts/upgrade.sh
```

升级流程：自动备份数据库 → 拉取新代码 → 重建镜像 → 重启服务 → 执行数据库迁移。

备份文件位于 `backups/` 目录。

## 卸载

```bash
bash scripts/uninstall.sh
```

会提示是否导出最终备份。卸载后 `.env`、证书和备份文件保留，需手动清理。

## 数据备份与恢复

```bash
# 手动备份
docker compose exec -T db pg_dump -U ngfw ngfw_monitor | gzip > backup.sql.gz

# 恢复
gunzip < backup.sql.gz | docker compose exec -T db psql -U ngfw ngfw_monitor
```

## 网络要求

服务器需开放以下端口：

| 端口 | 方向 | 用途 |
|------|------|------|
| 443 (或自定义) | 入站 | Web 管理界面 |
| 443 | 出站 → 防火墙 | PAN-OS XML API |
| 22 | 出站 → 防火墙 | SSH 采集 |
| 25/465/587 | 出站 → SMTP 服务器 | 报表邮件推送（可选） |
| 443 | 出站 → 互联网 | 飞书/企业微信通知（可选） |

## 常见问题

**Q: 容器无法访问防火墙？**
- 检查 Docker 网络模式，必要时使用 `network_mode: host`
- macOS Docker Desktop 需开启「Access local network」

**Q: 前端加载报证书错误？**
- 自签名证书首次需在浏览器点击"高级"→"继续访问"
- 或替换 `certs/` 下的证书为正式 CA 签发的证书

**Q: 磁盘增长太快？**
- 检查采集频率（默认 60 秒一次基础指标）
- 配置 TimescaleDB retention policy 自动清理历史数据
- `docker system prune` 清理无用镜像/日志

**Q: 如何修改 Web 端口？**
- 编辑 `docker-compose.yml` 中 frontend 的 ports 映射（容器内固定是 `8443`/`8080`，
  nginx 以非 root 运行绑不了特权端口，只改宿主侧的映射）
- `docker compose up -d frontend`

**Q: 飞书/企业微信通知报 `CERTIFICATE_VERIFY_FAILED`？AI 助手连不上模型服务？**

出网请求（飞书、企业微信、AI 模型服务）会校验 TLS 证书 —— 这些请求的 header 里带
API Key / webhook token，不校验等于把凭据交给任意中间人。**正常部署下这里不需要任何配置**：
对方用的是公共 CA 签发的证书，容器自带的信任库直接就能校验通过。

只有一种情况会报这个错：**开发机连着 GlobalProtect**，流量走进了有 TLS 解密代理的内网，
证书链被企业根 CA 重签。两个办法：

- 断开 GP，问题自动消失（推荐，也最接近生产的实际链路）
- 需要保持 GP 连接的话，把企业根 CA 挂进容器并指过去：

```bash
security find-certificate -a -p /Library/Keychains/System.keychain > certs/corp-root-ca.pem
```
```yaml
# docker-compose.yml 的 backend 和 worker 两个服务都要加
    volumes:
      - ./certs/corp-root-ca.pem:/etc/ssl/corp-ca.pem:ro
```
```bash
# .env
OUTBOUND_CA_BUNDLE=/etc/ssl/corp-ca.pem
```

`OUTBOUND_TLS_VERIFY=false` 可以整体关掉校验，但那会让 API Key 重新暴露在中间人面前，
只作为临时排障手段，不要带进生产。设备侧采集（PAN-OS API / SSH）不受这两个开关影响
—— 防火墙用的是自签名证书，那条链路本来就不校验。
