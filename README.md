# 防火墙集中监控系统 — Palo Alto NGFW 监控与分析平台

## 概述

面向 Palo Alto NGFW（PA-440/5500/7000 等）的集中监控和分析系统。通过 PAN-OS XML API 和 SSH CLI 定时采集设备指标，存储至 TimescaleDB，提供 Web Dashboard 进行可视化展示、告警推送、趋势分析和自动报表推送。

## 核心能力

- **多设备管理**：动态添加/移除被监控设备，支持 Panorama 设备发现
- **指标可扩展**：配置驱动 + 插件化采集，新指标零代码或低代码接入
- **历史趋势**：原始精度全量存储，查询时用户自选展示粒度
- **智能告警**：阈值告警 + 异常检测 + 趋势预测，支持飞书/邮件通知
- **自动报表**：周报/月报 PDF 自动生成，趋势分析+容量预测，邮件推送给管理层
- **ACC 数据分析**：应用流量 Top 10、威胁排名、严重性分布，支持 API 采集+CSV 导入
- **AI Copilot**：自然语言查询（"最近3天威胁Top 10"），LLM 意图解析+模板格式化，模型可配置
- **可移植部署**：Docker Compose 一键启动，笔记本到服务器无缝迁移

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11+, FastAPI, Celery, Redis |
| 前端 | React 18, TypeScript, ECharts, Ant Design |
| 数据库 | PostgreSQL 16 + TimescaleDB |
| 部署 | Docker Compose |
| 认证 | JWT + RBAC（Admin/Operator/Viewer） |

## 快速启动

```bash
# 复制环境配置
cp .env.example .env
# 编辑 .env 填写必要配置

# 笔记本环境
docker compose -f docker-compose.yml -f docker-compose.laptop.yml up -d

# 服务器环境
docker compose -f docker-compose.yml -f docker-compose.server.yml up -d
```

## 项目结构

```
NGFW_bytedance/
├── docker-compose.yml              # 基础服务定义
├── docker-compose.laptop.yml       # 笔记本资源限制
├── docker-compose.server.yml       # 服务器资源配置
├── .env.example                    # 环境变量模板
├── backend/                        # Python 后端
│   ├── app/
│   │   ├── main.py                 # FastAPI 入口
│   │   ├── config.py               # 配置管理
│   │   ├── models/                 # SQLAlchemy 模型
│   │   ├── api/                    # REST API 路由
│   │   ├── collectors/             # 采集器插件
│   │   ├── metrics/                # 指标定义与解析
│   │   ├── alerts/                 # 告警引擎
│   │   ├── copilot/               # AI Copilot（意图解析+格式化）
│   │   ├── reports/                # 报表生成（分析+图表+PDF）
│   │   ├── auth/                   # 认证与权限
│   │   └── tasks/                  # Celery 任务（采集+告警+报表）
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/                       # React 前端
│   ├── src/
│   │   ├── pages/                  # 页面组件
│   │   ├── components/             # 通用组件
│   │   └── api/                    # API 调用层
│   ├── Dockerfile
│   └── package.json
├── scripts/                        # 运维工具
│   ├── install.sh                  # 安装
│   ├── upgrade.sh                  # 升级
│   ├── uninstall.sh                # 卸载
│   └── status.sh                   # 状态检查
└── docs/                           # 项目文档
    ├── architecture.md
    └── api-spec.md
```
