# 架构设计文档

## 设计原则

1. **采集频率由人决定** — 系统永远不自动降频，只有管理员显式修改
2. **原始数据全量保留** — 存储层不丢点不合并，展示粒度由用户查询时选择
3. **指标可扩展** — 新指标优先通过配置接入，必要时才写采集插件
4. **环境无关** — 同一套代码通过环境变量和 compose overlay 适配不同部署规模
5. **系统不静默降级** — 资源不足时告警通知，由人决定如何处理

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     React Frontend                                │
│  仪表盘 | 设备管理 | 指标数据 | 告警管理 | ACC数据 | 报表 | AI助手 | 用户管理 │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTPS (nginx SSL termination)
┌────────────────────────────┴────────────────────────────────────┐
│                     FastAPI Backend                               │
│  Device API | Metrics API | Alert API | Auth API | Upload        │
│  DeviceGroup API | Users API | Reports API | Scope Filter        │
└──────┬─────────────────────┬────────────────────┬───────────────┘
       │                     │                    │
┌──────┴──────┐  ┌───────────┴──────────┐  ┌─────┴─────────┐
│ TimescaleDB │  │   Celery Workers     │  │    Redis       │
│ (数据存储)   │  │ (采集+告警+报表生成)  │  │  (队列+缓存)   │
└─────────────┘  └───────────┬──────────┘  └───────────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
        ┌─────┴─────┐ ┌─────┴─────┐ ┌─────┴─────┐
        │ PAN-OS    │ │ SSH CLI   │ │ Panorama  │
        │ XML API   │ │           │ │ API       │
        └───────────┘ └───────────┘ └───────────┘
```

## 数据流

### 采集流

```
Celery Beat (定时触发)
  → Celery Worker 接收任务
    → 查询 Metric Registry (获取采集配置)
      → 调用对应 Collector 插件
        → Collector 访问设备 (API/SSH)
          → Parser 解析返回数据
            → 写入 TimescaleDB
              → Alert Engine 评估规则
                → (触发) Notifier 发送通知
```

### 查询流

```
前端选择: 设备 + 指标 + 时间范围 + 粒度
  → Backend 生成 time_bucket 查询
    → TimescaleDB 实时聚合
      → 返回数据点 (avg/max/min)
        → 前端 ECharts 渲染
```

### AI Copilot 流

```
用户自然语言输入 (如 "最近3天威胁Top 10")
  → 后端发送至 LLM (仅发送用户问题，不含数据)
    → LLM 返回结构化意图 {action, params}
      → 后端执行对应 API 查询 (内部调用，数据不外泄)
        → 模板格式化为 Markdown 表格/摘要
          → 前端渲染展示
```

> 设计要点：LLM 仅用于意图解析，防火墙数据永远不经过云端模型。

## 模块职责

### Collectors（采集器）

| 采集器 | 职责 | 协议 | 调度间隔 |
|--------|------|------|----------|
| PanosApiCollector | PAN-OS XML API 调用 | HTTPS | 60s |
| PanosSshCollector | SSH CLI 命令执行 | SSH | 60-300s |
| PanosReportCollector | Report API ACC 数据采集 | HTTPS | 3600s |
| PanoramaCollector | Panorama Report API | HTTPS | - |
| FileUploadCollector | 用户上传 CSV 文件解析 | - | 手动 |

### Alert Engine（告警引擎）

```
告警规则类型：
├── ThresholdRule      — 阈值告警（即时）
├── AnomalyRule        — 统计异常检测（Z-score/IQR）
└── PredictionRule     — 趋势预测（Prophet）
```

### Notifiers（通知渠道）

```
通知渠道：
├── FeishuNotifier     — 飞书群机器人 Webhook / 应用消息
├── EmailNotifier      — SMTP 邮件
└── (扩展预留)         — Slack / 自定义 Webhook
```

### Reports（报表模块）

```
报表生成流程：
Celery Beat (cron 调度)
  → generate_report_task(template_id)
    → 查询 TimescaleDB 时间范围内指标数据
      → analysis.py: numpy 线性回归趋势/预测/环比
        → charts.py: matplotlib 渲染图表 → PNG base64
          → generator.py: Jinja2 HTML 模板 + 数据
            → weasyprint: HTML → PDF
              → 保存文件 + 记录 report_history
                → aiosmtplib: PDF 附件邮件发送
```

```
报表模块组成：
├── analysis.py        — 趋势分析（polyfit 线性回归）、容量预测、排名计算
├── charts.py          — matplotlib 图表（趋势折线、饼图、柱状图、严重性分布）
├── generator.py       — PDF 生成核心（组装数据+图表+模板→PDF）
├── templates/         — Jinja2 HTML 报表模板（含模板化自然语言结论）
└── init_builtin.py    — 预置模板初始化（周报/月报）
```

## 数据模型概览

### 核心表

- `users` — 用户账号与角色（admin/operator/viewer）
- `user_group_scopes` — 用户-设备分组权限关联（多对多）
- `devices` — 被监控设备（IP、凭据、型号、状态、分组归属）
- `device_groups` — 设备分组（按地理/业务分组）
- `metric_definitions` — 指标定义（采集配置、解析规则、12 个内置）
- `metric_data` — 时序数据（hypertable，含 JSONB labels 扩展字段）
- `alert_rules` — 告警规则配置
- `alert_events` — 告警事件历史
- `notification_channels` — 通知渠道配置
- `report_templates` — 报表模板（类型、调度 cron、指标列表、收件人）
- `report_history` — 报表生成历史（PDF 文件路径、状态、发送时间）

### TimescaleDB 特性使用

- `metric_data` 表作为 hypertable，按时间分片
- 无损压缩策略（compress_after 可配）
- time_bucket 实时聚合查询
- 数据保留策略（retention policy，过期自动清除）

## 部署拓扑

### 笔记本（开发/轻量使用）

- 单 Docker Compose，全部容器同机
- Worker × 1，采集并发 5
- 内存总消耗 ~1.2GB

### 服务器（生产/团队使用）

- 同 Docker Compose，overlay 放开资源
- Worker × 2-4，采集并发 20+
- 内存建议 8GB+
- 外挂数据卷，定时备份

## ACC 数据体系

ACC (Application Command Center) 数据分为两种采集方式：

### 自动采集（Report API）
- 每小时调用 PAN-OS Report API 获取 top-applications / top-spyware-threats
- 存储：metric_name=acc_application/acc_threat, value=bytes/count, labels={application/threat_name, severity, ...}
- 调度：interval-based，检查 MAX(timestamp) 判断是否到期

### 手动导入（CSV Upload）
- 支持 traffic/threat 两种 CSV 格式
- 每行解析为独立 MetricData 记录，累积形成趋势

### 可视化
- 趋势图：time_bucket 聚合，Top 10 堆叠折线
- 饼状图：Top 10 占比分布
- 排名表：完整排名，支持多列排序

## 权限模型

### RBAC（角色控制操作）
- admin: 全部操作
- operator: 设备/告警管理，不能管理用户和系统设置
- viewer: 只读

### Scope（分组控制数据可见性）
- 用户可被分配到多个设备分组
- 无 scope 分配 = 全局访问（向后兼容）
- 所有设备数据相关 API 经过 scope 过滤

## 设备状态管理

- 采集成功（任一指标）→ status=online, 更新 last_seen
- 采集尝试全部失败 → status=offline
- 无采集尝试（所有指标不到期）→ 不变更状态
- 新设备添加时通过 keygen API 验证可达性

## 报表系统

### 预置模板

| 模板 | 调度 | 覆盖范围 | 指标 |
|------|------|----------|------|
| 周报 | 每周一 08:00 | 过去 7 天 | CPU、会话数、应用 Top10、威胁 Top10+严重性 |
| 月报 | 每月 1 日 08:00 | 过去 30 天 | 同上 + 内存、PD、接口吞吐 |

### 分析能力

- **趋势计算**: numpy polyfit 线性回归，输出斜率 (每小时/每周变化率)
- **容量预测**: 按当前斜率外推，预测何时达到告警阈值
- **环比**: 当前周期 vs 上一周期的变化百分比
- **排名**: Top-N 应用/威胁，含流量、会话数、严重性分布

### PDF 生成

- 模板: Jinja2 HTML + CSS 排版
- 图表: matplotlib 服务端渲染 → base64 PNG 嵌入 HTML
- 转换: weasyprint (HTML+CSS → PDF)
- 存储: Docker volume `reportdata` 在 worker/backend 容器间共享
- 路径: `/app/data/reports/YYYY/MM/<type>_YYYYMMDD.pdf`

### 模板化文字结论

每个指标段落末尾附模板化自然语言结论（Jinja2 条件渲染），无需 LLM：
- 趋势上升 → 预测到达阈值时间，建议关注
- 趋势平稳 → 运行正常
- 趋势下降 → 态势改善
- 报表末尾汇总"综合评估"段落

## 安全考虑

- 设备凭据（API Key、SSH 密码）加密存储
- JWT Token 短期有效 + Refresh Token 续期
- RBAC 三级权限控制 + Scope 数据隔离
- 密码策略：8位+大小写+数字+特殊字符，常见密码黑名单
- HTTPS 通信（自签名证书 + nginx SSL 终止）
- API 限流防爆破
