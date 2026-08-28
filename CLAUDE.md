# ===== 通用AI编码行为规约（参考社区 Capsey / Karpathy best‑practice） =====
## 思考前置
1. 动手改代码前，优先读取相关现有源码，**禁止凭空臆测代码逻辑**；有歧义、多种可能性时主动提问，不要默默自选方案执行。
2. 明确你的假设与取舍；如果有更简单实现路径，请主动提出来。
## 简单优先
3. 追求最小可行实现，拒绝过度设计；只使用一次的逻辑不要强行抽象。
4. 不要额外增加需求以外的功能，不做画蛇添足优化。
## 外科手术式修改（最重要）
5. **只修改任务直接相关的代码**；不要顺手重构、格式化、清理周边无关代码。
6. 每一处改动都要可以追溯到用户需求；没有被要求修改的文件/逻辑尽量不动。
7. 新增依赖必须先征询确认，不要私自引入第三方包。
## 验证原则
8. 修改完成后给出可复现的验证、测试步骤；修bug优先考虑复现case，再修复。
9. 如果无法本地运行测试，明确告知风险，不要主观宣称“代码已经可以正常运行”。
## 输出与沟通
10. 输出变更优先给出diff视角；关键改动简要解释意图。
11. 遇到阻塞直接说明，不要编造不存在函数、路径、接口。

# NGFW Monitor — Palo Alto 防火墙监控与分析平台
## 项目概述
为大客户监控 Palo Alto NGFW 设备（PA-5450/5220/7050 等）的集中平台。通过 PAN-OS XML API 和 SSH CLI 定时采集设备指标，提供 Web Dashboard 可视化、告警推送和趋势分析。
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

## 项目状态

核心功能均已上线并端到端验证（PA-440）。已完成项与版本历史见 `CHANGELOG.md` 和 `git tag -n99`，此处不重复。

未完成：Panorama 设备发现、数据保留策略自动执行、多设备（PA-5500/7000）接入验证。
待办、优化事项、已知 bug 见 `docs/roadmap.md`。

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

# 装凭据门禁（clone 后跑一次；hook 本体在 scripts/githooks/，只有 hooksPath 是本机配置）
bash scripts/install-git-hooks.sh

# 发布前安全关卡（确定性，只报相对 security/*.json baseline 的新增）
# CI 也自动跑：push main / tag v* / PR（.github/workflows/security-gate.yml）
bash scripts/security-gate.sh
bash scripts/test-backend.sh   # 后端测试；脚本头注释解释了为什么绕 Docker 跑
```

## 目录结构（只列看名字猜不到的）

- `backend/app/collectors/` — 采集器插件（panos_api / panos_ssh / panorama / panos_report / file_upload）；本目录有独立 CLAUDE.md 记 ACC 报表 API 的坑
- `backend/app/tasks/collect.py` — 核心采集调度（per-device 批量、命令去重、连接复用、设备状态自动检测）
- `backend/app/tasks/locks.py` — 采集防重入锁 + 跳过/耗时/队列深度等运行时状态（Redis）
- `backend/app/tasks/health.py` — 采集链路自检任务；六个信号的定义与阈值在 `app/alerts/health.py`
- `backend/app/metrics/` — `builtin.yaml` 内置指标定义、`parser.py` 通用解析器、`rate.py` 计数器→速率差分 SQL
- `backend/app/alerts/notify.py` — 通知冷却判定 + 渠道分发（指标告警与自检告警共用）
- `backend/app/models/setting.py` — key-value 系统设置（AI 配置等动态项）
- `backend/app/reports/` — 趋势分析 / matplotlib 图表 / PDF 生成 / HTML 模板；调度在 `tasks/report.py`
- `scripts/` — install / upgrade / uninstall / status
- 其余 `api/`、`models/`、`auth/`、`copilot/`、`frontend/src/pages/` 按名字对应，需要时直接 ls

# ===== 自动踩坑记忆与更新约束 =====
1. 本轮任务完成、bug修复结束后，自动提炼本次开发的踩坑点与AI犯错记录，仅增量追加内容，不覆盖、不修改原有核心规约
2. 本文件总行数严格控制在140行以内，新增高频规则前自动清理过时、失效的旧禁令
3. 高频重复出现的硬性规则追加至当前章节；低频、特定场景的踩坑统一写入 `pitfalls/history-pitfalls.md`；只在改某个模块时才用到的坑写进该模块目录下的 CLAUDE.md（按需加载，不占常驻上下文）
4. 仅允许修改踩坑相关章节，不得改动上方通用编码规约、多Agent协作规则
5. 更新完成后输出本次新增的规则清单，供人工审核确认

## 已知注意事项

只记会再次踩到的坑。能从代码直接读出来的实现细节不写在这里。
### PAN-OS 报表 API（ACC 数据）

- 报表读哪个库决定数字对不对：应用流量必须读 `trsum`，不是 `appstat`（实测同一小时 253MB vs 1407MB）
- 完整的坑（dynamic vs predefined、三种静默失效、跨报表去重用 max、严重性配额、tid 做键、设备时区）见 `backend/app/collectors/CLAUDE.md`，改 ACC 采集前必读

### 采集调度

- 桶时间戳对齐后幂等，重复采集用 `ON CONFLICT DO NOTHING`；调度判断"是否该采"必须比对**桶身份**而不是经过时间（数据点时间戳永远滞后 now）
- 空桶不产生数据行，靠 `_bucket::<metric>` 标记区分"采过但是空"和"没采过"，否则 beat 每分钟会把同一个空桶重复问 15 次。回补历史用 `collect(…, bucket=(start, end))`，补数要连标记一起删掉重写
- 多个指标共用一条命令（`show session info` 喂 4 个），采集按命令去重后再分发响应。SSH 每条命令固定 4s settle + 最多 8s 排空，重复命令是秒级浪费
- 计数器类指标存原始累计值，**差分在查询期做**（`app/metrics/rate.py`）。差分为负说明设备重启或计数器回绕，该点丢弃；lookback 要越过 `:start`，否则首个样本没有前值
- `worker_prefetch_multiplier=1`：worker 预取的任务在队列深度里看不见，积压会藏在 worker 内存里，还会在里面熬过 `expires` 被丢掉
- 跳过计数是**增量消费**的（`take_skip_deltas` 读一次就推进水位），所以「跳周期」是事件不是状态，下次自检没有新增就自动恢复；API 展示读累计值，不推进水位
- PA-440 管理面资源有限，并发连接不能太多（当前已优化为单连接复用）
- `cpu_usage` 是**管理面**（top），数据面 CPU 得用 `show running resource-monitor`，同一时刻实测能差几十个点。top 那行 `%Cpu(s)` 的字段和**不等于 100**（实测 33~93，4 核），所以单读任何一个字段都错：`us` 漏掉 sy/ni（忙时差 11 点），`id` 完全不可信（`100-id` 在进程只占 18% 时报 86%）。现为"非 id 字段求和"，改法拿真机进程列表 %CPU 之和核对过——**改这个指标必须用真机采样验，自造样本三次都看着合理但错**。历史数据三段口径（`us` → `100-id` → 求和），跨段有台阶

### 数据库与 ORM

- **建库靠 `create_all`，没有 Alembic**：加新表可以，**加新列和给 postgres enum 加值不行**。所以速率配置塞在已有的 `parser` JSON 里，采集健康度规则复用 `AlertType.threshold` + 哨兵 `metric_name`，而不是加新枚举值
- **SQLAlchemy autoflush 陷阱**：`session.add(x)` 后在同一 session 里 `SELECT COUNT` 会把待写入的这行 flush 出去并数进结果。通知冷却曾因此把每一条真实告警都静音了（事件照样入库，就是没人收到通知）。冷却判定必须在 `session.add` **之前**做
- asyncpg 不支持 INTERVAL 参数绑定，SQL 中必须内联 INTERVAL 字符串
- Celery prefork worker 不能共享 async engine，每个 task 需创建独立 engine 并 dispose

### 分组授权（scope）

- scope 是**逐接口手写**的，没有集中拦截点。任何读 `metric_data` / `alert_events` /
  `devices` 的新接口都要显式过 `app/auth/scope.py`；跨设备聚合时"没传 device_id"**不等于
  不过滤**（用 `scoped_device_sql()`），授权检查也不能只写在 if/elif 的某个分支里
- **Copilot 的每个 action 都是一条独立数据出口**，加 action 按"新接口"审授权，不是按"查询函数"
- 安全关卡和扫描器对越权是**零覆盖**（只匹配已知坏模式）：加接口 / 加 action 后必须跑一次 `/security-review` 看 diff，这是唯一能发现 scope 漏掉的环节
- 凭据字段脱敏（`_is_secret_key`）必须配回写保护：前端会把读到的 `***` 原样提交回来，
  直接落库就把真凭据覆盖了。约定掩码值 = 保持不变

### 告警与部署

- 通知渠道的「测试发送」按钮验证的是渠道配置，**不等于告警链路通了**——它绕过冷却和事件写入
- 采集健康度规则是内置的，删了下次启动会重建（`_seed_health_alert_rule`），**停用方式是关开关**；管理员改过的 `condition` 不会被升级覆盖
- macOS Docker Desktop 需开启「Access local network」才能从容器访问 LAN 设备
- weasyprint 需要系统级依赖（libcairo2, libpango, libgdk-pixbuf, fonts-wqy-zenhei），已在 Dockerfile 中安装
