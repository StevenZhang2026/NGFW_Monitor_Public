# 架构设计文档

## 设计原则

1. **采集频率由人决定** — 系统永远不自动降频，只有管理员显式修改
2. **原始数据全量保留** — 存储层不丢点不合并，展示粒度由用户查询时选择
3. **指标可扩展** — 新指标优先通过配置接入，必要时才写采集插件
4. **环境无关** — 同一套代码通过环境变量和 compose overlay 适配不同部署规模
5. **系统不静默降级** — 资源不足时告警通知，由人决定如何处理

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                     React Frontend                            │
│  仪表盘 | 设备管理 | 指标数据 | 告警管理 | ACC数据 | 用户管理   │
└────────────────────────────┬────────────────────────────────┘
                             │ HTTPS (nginx SSL termination)
┌────────────────────────────┴────────────────────────────────┐
│                     FastAPI Backend                           │
│  Device API | Metrics API | Alert API | Auth API | Upload    │
│  DeviceGroup API | Users API | Scope Filter                  │
└──────┬─────────────────────┬────────────────────┬───────────┘
       │                     │                    │
┌──────┴──────┐  ┌───────────┴──────────┐  ┌─────┴─────────┐
│ TimescaleDB │  │   Celery Workers     │  │    Redis       │
│ (数据存储)   │  │   (采集+告警+预测)    │  │  (队列+缓存)   │
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

## 安全考虑

- 设备凭据（API Key、SSH 密码）加密存储
- JWT Token 短期有效 + Refresh Token 续期
- RBAC 三级权限控制 + Scope 数据隔离
- 密码策略：8位+大小写+数字+特殊字符，常见密码黑名单
- HTTPS 通信（自签名证书 + nginx SSL 终止）
- API 限流防爆破
