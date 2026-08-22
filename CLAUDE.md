# NGFW Monitor — Palo Alto 防火墙监控与分析平台

## 项目概述

为字节跳动团队监控 Palo Alto NGFW 设备（PA-5450/5220/7050 等）的集中平台。通过 PAN-OS XML API 和 SSH CLI 定时采集设备指标，提供 Web Dashboard 可视化、告警推送和趋势分析。

## 技术栈

- 后端: Python 3.11+, FastAPI, Celery + Redis, SQLAlchemy
- 前端: React 18, TypeScript, Vite, Ant Design, ECharts
- 数据库: PostgreSQL 16 + TimescaleDB
- 部署: Docker Compose（笔记本 / 服务器两种 overlay）

## 关键设计约束

1. **采集频率由管理员控制** — 系统永远不自动降频。有默认值，管理员可修改，系统不自作主张
2. **原始数据全量保留** — 存储层不丢点不合并不降采样。展示粒度由用户查询时自由选择
3. **指标可扩展** — 80% 场景通过配置（YAML/Web UI）添加新指标零代码；20% 场景写新 Collector 插件
4. **环境无关可迁移** — 同一套代码通过 .env + compose overlay 适配笔记本/服务器，数据 pg_dump 迁移
5. **资源不足时明确告警** — 不静默降级，通知用户决定扩容还是调整

## 设备环境

- 已接入: PA-440（192.168.1.254），PAN-OS 11.x
- 待接入: PA-5500 系列、PA-7000 系列（接口命名和传感器布局不同，采集逻辑已动态适配）
- 有 Panorama（用于设备发现和 Report API，但高频指标仍直连设备采集）
- 认证: SSH 用户名密码（添加设备时提供），API Key 自动通过 keygen 获取

## 当前进度

- [x] 架构设计完成
- [x] 项目骨架代码生成（后端 + 前端 + Docker）
- [x] API 接口规范文档
- [x] 端到端验证（PA-440 已接入，所有内置指标正常采集）
- [x] 前端完善（仪表盘、设备管理、指标数据、告警管理、系统设置）
- [x] HTTPS（自签名证书 + nginx 终止 SSL）
- [x] 采集连接复用（每设备单任务，共享 HTTPS/SSH 会话）
- [x] 多实例指标（接口流量、温度传感器按 instance 分别展示）
- [x] 告警体系（规则 CRUD、飞书/企业微信/邮件通知渠道、测试发送）
- [x] 自定义指标（Web UI 配置命令 + 解析规则，自动采集）
- [x] 密码强度策略（8位+大小写+数字+特殊字符，常见密码黑名单）
- [x] 设备分组管理（分组 CRUD、设备归组、用户 Scope 权限过滤）
- [x] ACC 数据体系（Report API 自动采集 + CSV 导入 + 趋势/排名/饼图可视化）
- [x] 仪表盘四宫格（CPU、Packet Descriptor、应用 Top 10、威胁 Top 10）
- [x] 设备状态自动检测（采集失败→offline，采集成功→online）
- [x] 用户管理（CRUD、角色分配、Scope 分组权限）
- [ ] 告警体系端到端验证（触发→通知→恢复）
- [ ] Panorama 设备发现
- [ ] 数据保留策略自动执行
- [ ] 多设备接入验证

## 下一步

1. 告警规则端到端验证（配置阈值规则 → 触发 → 收到通知 → 恢复通知）
2. 接入更多设备（PA-5500/PA-7000 系列）验证兼容性
3. 数据保留策略自动执行（TimescaleDB retention policy）
4. Panorama 设备自动发现
5. 性能调优（采集间隔精细控制、worker 并发优化）

## 常用命令

```bash
# 启动所有服务
docker compose up -d

# 重建并重启（代码修改后）
docker compose build backend frontend worker beat && docker compose up -d

# 前端访问
# https://localhost:3000 (自签名证书)

# 后端单独开发
cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload

# 前端单独开发
cd frontend && npm install && npm run dev

# 查看采集日志
docker compose logs worker --tail 20 -f
```

## 目录结构

- `backend/app/collectors/` — 采集器插件（panos_api, panos_ssh, panorama, panos_report, file_upload）
- `backend/app/tasks/collect.py` — 核心采集调度（per-device 批量采集，连接复用，状态自动检测）
- `backend/app/tasks/alert.py` — 告警评估任务
- `backend/app/metrics/builtin.yaml` — 内置指标定义（12 个，含 ACC 应用/威胁）
- `backend/app/metrics/parser.py` — 通用解析器（xpath, xpath_multi, regex, regex_multi, regex_cdata）
- `backend/app/alerts/` — 告警引擎（threshold/anomaly/prediction）+ 通知渠道（feishu/wechat/email）
- `backend/app/auth/` — 认证鉴权（JWT, password_policy, scope 权限过滤）
- `backend/app/api/` — REST API 路由（devices, metrics, alerts, auth, users, device_groups, upload）
- `backend/app/models/` — 数据模型（device, device_group, metric, alert, user）
- `frontend/src/pages/` — 前端页面（Dashboard, Devices, Metrics, Alerts, Settings, Upload/ACC, Users）
- `certs/` — 自签名 TLS 证书（.gitignore）
- `docs/` — 架构文档和 API 规范

## 已知注意事项

- macOS Docker Desktop 需开启「Access local network」才能从容器访问 LAN 设备
- PA-440 管理面资源有限，并发连接不能太多（当前采集已优化为单连接复用）
- asyncpg 不支持 INTERVAL 参数绑定，SQL 中必须内联 INTERVAL 字符串
- Celery prefork worker 不能共享 async engine，每个 task 需创建独立 engine 并 dispose
- PA-440 Report API 返回 `<report>` 根元素（非标准的 `<response>`），解析时需特殊处理
- PA-440 有效 report 名称：top-applications, top-spyware-threats, top-viruses, top-url-categories
- PA-440 实验室环境流量少，Report API 可能返回空结果（机制正常，只是无数据）
