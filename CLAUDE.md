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
- [x] ACC 实时采集重构（Log Query API 替代 Report API，时间戳对齐整点）
- [x] ACC 采集改为设备侧聚合（dynamic report + 15 分钟对齐桶，采集成本与日志量无关）
- [x] 安装工具套件（install/upgrade/uninstall/status 脚本 + INSTALL.md）
- [x] 报表模块（周报/月报自动生成 PDF、趋势分析+容量预测、邮件推送、Web 管理）
- [x] 告警体系优化（通知冷却、活跃告警计数、批量确认、飞书通知已验证）
- [x] AI Copilot 助手（自然语言查询、LLM 意图解析、模板格式化、模型可配置）
- [x] ACC 图表修复（趋势图 tooltip 时间轴对齐、趋势图/饼图颜色统一）
- [x] 交互式系统架构图（archify 生成）
- [x] 采集防重入（per-device Redis 锁，跳过而非并发采同一台设备）
- [x] 采集命令去重 + interval 真正生效（单次采集 19.9s → 9.5s）
- [x] 计数器类指标查询期差分（interface_throughput 等按速率返回，原始累计值不改动）
- [x] 采集链路自检告警（停采/耗时/跳周期/队列积压/间隔无法满足/设备离线，六个信号）
- [ ] Panorama 设备发现
- [ ] 数据保留策略自动执行
- [ ] 多设备接入验证

## 下一步

1. 报表邮件端到端验证（配置 SMTP → 自动发送 → 收件人收到 PDF）
2. 接入更多设备（PA-5500/PA-7000 系列）验证兼容性
3. 数据保留策略自动执行（TimescaleDB retention policy）
4. Panorama 设备自动发现
5. 性能调优（采集间隔精细控制、worker 并发优化）
6. Copilot 能力扩展（支持更多查询类型、多轮对话）
7. `cpu_usage` 曾采到 112.3%（`%Cpu(s)` 不应超过 100），需查解析规则——影响 CPU 阈值告警和容量预测
8. 大设备接口白名单可配置（PA-5450/7050 逻辑接口多，全采会拉长采集耗时）

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
- `backend/app/tasks/collect.py` — 核心采集调度（per-device 批量采集，命令去重，连接复用，状态自动检测）
- `backend/app/tasks/locks.py` — 采集防重入锁 + 跳过/耗时/队列深度等运行时状态（Redis）
- `backend/app/tasks/alert.py` — 告警评估任务
- `backend/app/tasks/health.py` — 采集链路自检任务（每 120s，事件去重+自动恢复）
- `backend/app/metrics/builtin.yaml` — 内置指标定义（12 个，含 ACC 应用/威胁）
- `backend/app/metrics/parser.py` — 通用解析器（xpath, xpath_multi, regex, regex_multi, regex_cdata）
- `backend/app/metrics/rate.py` — 计数器→速率的查询期差分 SQL
- `backend/app/alerts/` — 告警引擎（threshold/anomaly/prediction）+ 通知渠道（feishu/wechat/email）
- `backend/app/alerts/health.py` — 采集链路自检的信号定义（六个信号 + 判定阈值）
- `backend/app/alerts/notify.py` — 通知冷却判定 + 渠道分发（指标告警和自检告警共用）
- `backend/app/auth/` — 认证鉴权（JWT, password_policy, scope 权限过滤）
- `backend/app/copilot/` — AI Copilot 模块（intent 意图解析, formatter 结果格式化）
- `backend/app/api/` — REST API 路由（devices, metrics, alerts, auth, users, device_groups, upload, reports, copilot）
- `backend/app/models/` — 数据模型（device, device_group, metric, alert, user, report）
- `backend/app/reports/` — 报表生成（analysis 趋势分析, charts matplotlib 图表, generator PDF 生成, templates HTML 模板）
- `backend/app/tasks/report.py` — 报表调度任务（生成 + 邮件发送）
- `backend/app/models/setting.py` — 系统设置模型（key-value 存储，用于 AI 配置等动态设置）
- `frontend/src/pages/` — 前端页面（Dashboard, Devices, Metrics, Alerts, Settings, Upload/ACC, Users, Reports, Copilot）
- `scripts/` — 运维工具（install.sh, upgrade.sh, uninstall.sh, status.sh）
- `certs/` — 自签名 TLS 证书（.gitignore）
- `docs/` — 架构文档和 API 规范

## 已知注意事项

- macOS Docker Desktop 需开启「Access local network」才能从容器访问 LAN 设备
- PA-440 管理面资源有限，并发连接不能太多（当前采集已优化为单连接复用）
- asyncpg 不支持 INTERVAL 参数绑定，SQL 中必须内联 INTERVAL 字符串
- Celery prefork worker 不能共享 async engine，每个 task 需创建独立 engine 并 dispose
- PA-440 Report API 返回 `<report>` 根元素（非标准的 `<response>`），解析时需特殊处理
- ACC 采集用 `reporttype=dynamic`，**不能用 `predefined`**：predefined 报表是设备每天预生成的批次，会静默忽略 `period`，永远返回前一整天的快照
- dynamic 报表的 `query` 参数只是 `period` 窗口内的二次过滤，**不能用来定义时间窗口**；要显式窗口必须用原生 `start-time` / `end-time`（设备本地时间，`end-time` 含端点，所以桶尾要减 1 秒）
- **报表读哪个库决定数字对不对**：`top-applications-summary` 读 `appstat`（App-ID 扫描统计），不是 ACC 界面 Application Usage 的来源，实测同一小时 appstat 253MB vs `trsum` 1407MB，另一小时 2.5MB vs 590MB（少报百倍，但每个应用自己的字节数是对的——它是**漏应用**不是算错）。应用流量必须走 `trsum`。威胁不受影响：`top-attacks-acc` 本来就读 `thsum`，和内联 thsum 报表逐字节一致
- 应用流量用**内联自定义动态报表**：`reportname=custom-dynamic-report` + `cmd=<type><trsum><aggregate-by>…</aggregate-by><values>…</values></trsum></type>`。`parser.reports` 支持 `database` / `aggregate_by` / `values` / `sortby` 形态，也兼容原来的命名报表形态
- **custom-dynamic-report 会静默忽略 URL 上的 `start-time`/`end-time`**（回显 `1970/01/01 08:00:00`、返回 0 行），时间窗口必须写在 `cmd` 里面；`<period>custom</period>` 和 `<period><start>…</start></period>` 都会让报表生成失败
- `trsum` 的 `values` 只能要 `bytes` / `sessions`，**加 `packets` 会让设备返回 success 但 0 行**——和空桶无法区分，是静默失效。`thsum` 的值字段是 `count` 不是 `threats`（写 `threats` 同样静默返回 0 行）
- trsum 窗口会吸附到 15 分钟桶边界：`period=last-hour`（19:43:47~20:43:46）和显式 19:30~20:29 返回完全相同的数字。实测四个 15 分钟桶 61.62+169.10+101.66+257.34 = 589.72MB 正好等于整小时
- `PanosReportCollector.collect(device, metric_def, bucket=(start_utc, end_utc))` 可以指定桶回补历史（汇总库保留历史）；补数时要连 `_bucket::<metric>` 标记一起删掉重写，否则调度会认为该桶已采过
- dynamic 报表名和 predefined 是两套：应用用 `top-applications-summary`，威胁用 `top-attacks-acc`（已覆盖 spyware/vulnerability/virus 全部子类型）
- 不要把 `top-spyware-threats-summary` / `top-spyware-download-summary` 与 `top-attacks-acc` 合并采集——它们返回相同行，会把 spyware 重复计数
- 威胁必须按 `tid` 做存储键：不同 tid 会共用同一个显示名（如 3 条不同的 "HTTP SQL Injection Attempt"），按名字做键会撞主键
- 部分 spyware/DNS-security 威胁设备本身没有名字，`threatid` 直接返回数字 ID（如 109010006），设备 ACC 界面也是这样显示
- 桶时间戳对齐后是幂等的，重复采集用 `ON CONFLICT DO NOTHING` 跳过；调度判断"是否该采"必须比对**桶身份**而不是经过时间（数据点时间戳永远滞后 now）
- 空桶（无流量）不产生数据行，靠 `_bucket::<metric>` 标记行区分"采过但是空"和"没采过"，否则 beat 每分钟会把同一个空桶重复问设备 15 次
- 设备时区从 `show clock` 推导，不能硬编码（CST 既是中国也是美国中部）
- 威胁排名按次数排序 + topn 截断，罕见但危险的事件会被高频噪声挤掉（实测 3 条 low 4184/2265/724 次挤掉了 10 条 medium，含只出现 1 次的 Malicious Windows Executable）。所以 critical / high 各跑一次 `query=(severity eq ...)` 独占 topn 配额，**保证可见**；medium 及以下仍受挤压
- 严重性过滤 pass 返回的是总报表的**严格子集，count 逐字节相同**，所以 `_merge` 跨报表用 `max` 而不是求和（求和会把重叠行全部翻倍）；单个报表内部仍求和
- `query` 只能在 `start-time`/`end-time` 窗口**内**过滤，不影响窗口本身（设备回显的 window 不变）
- PA-440 实验室环境流量少，Report API 可能返回空结果（机制正常，只是无数据）
- weasyprint 需要系统级依赖（libcairo2, libpango, libgdk-pixbuf, fonts-wqy-zenhei），已在 Dockerfile 中安装
- **建库靠 `create_all`，没有 Alembic**：加新表可以，**加新列和给 postgres enum 加值不行**（`create_all` 不会 `ALTER`）。所以速率配置塞在已有的 `parser` JSON 里，采集健康度规则复用 `AlertType.threshold` + 哨兵 `metric_name`，而不是加新枚举值
- **SQLAlchemy autoflush 陷阱**：`session.add(event)` 后在同一 session 里 `SELECT COUNT` 会把待写入的这行 flush 出去并数进结果。通知冷却曾因此把每一条真实告警都静音了（事件照样入库，就是没人收到通知）。冷却判定必须在 `session.add` **之前**做
- 通知渠道的「测试发送」按钮验证的是渠道配置，**不等于告警链路通了**——它绕过冷却和事件写入
- 多个指标共用一条命令（`show session info` 喂 4 个，`show system resources` 喂 2 个），采集按命令去重后再把响应分发给各指标；SSH 每条命令固定 4s settle + 最多 8s 排空，重复命令是秒级浪费
- 计数器类指标（接口收发字节数）存原始累计值，**差分在查询期做**（`app/metrics/rate.py`，`lag()` 按 `(device_id, metric_name)` 分区）。差分为负说明设备重启或计数器回绕，该点丢弃；lookback 要越过 `:start` 否则首个样本没有前值
- 采集健康度规则是内置的，删了下次启动会重建（`_seed_health_alert_rule`），**停用方式是关开关**。管理员改过的 `condition` 不会被升级覆盖，只会补上新版本新增的键
- 队列深度只能看到还在 Redis 里的任务，worker 预取的部分不可见，所以 `worker_prefetch_multiplier=1`——否则积压藏在 worker 内存里，还会在里面熬过 `expires` 被丢掉
- 跳过计数是**增量消费**的（`take_skip_deltas` 读一次就推进水位），所以「跳周期」是事件不是状态，下次自检没有新增就自动恢复；API 展示读的是累计值，不推进水位
- 报表 PDF 通过 Docker volume（reportdata）在 worker 和 backend 容器间共享
