# API 接口规范

Base URL: `/api/v1`

## 认证

所有接口（除登录/注册）需携带 JWT Token：
```
Authorization: Bearer <token>
```

---

## Auth 认证模块

### POST /auth/login
登录获取 Token。

**Request:**
```json
{
  "username": "admin",
  "password": "***"
}
```

**Response:**
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

### POST /auth/refresh
刷新 Token。

### GET /auth/me
获取当前用户信息。

---

## Users 用户管理 (Admin)

### GET /users
获取用户列表。

### POST /users
创建用户。

```json
{
  "username": "operator1",
  "email": "op1@example.com",
  "role": "operator",
  "password": "***"
}
```

### PUT /users/{id}
修改用户信息/角色。

### DELETE /users/{id}
删除用户。

---

## Devices 设备管理

### GET /devices
获取设备列表。

**Query Params:**
- `status` — online/offline/all
- `page`, `page_size` — 分页

**Response:**
```json
{
  "items": [
    {
      "id": "uuid",
      "name": "PA-5450-01",
      "hostname": "10.1.1.1",
      "model": "PA-5450",
      "panos_version": "11.1.2",
      "serial": "0123456789",
      "status": "online",
      "ha_state": "active",
      "created_at": "2024-01-01T00:00:00Z",
      "last_seen": "2024-01-01T12:00:00Z"
    }
  ],
  "total": 10,
  "page": 1,
  "page_size": 20
}
```

### POST /devices
添加设备。

```json
{
  "name": "PA-5450-01",
  "hostname": "10.1.1.1",
  "auth_type": "api_key",
  "api_key": "LUFRPT...",
  "ssh_username": "admin",
  "ssh_password": "***",
  "collect_enabled": true
}
```

### PUT /devices/{id}
修改设备配置。

### DELETE /devices/{id}
移除设备（停止采集，可选保留历史数据）。

### POST /devices/{id}/test-connection
测试设备连通性。

---

## Metrics 指标模块

### GET /metrics/definitions
获取所有指标定义。

**Response:**
```json
{
  "items": [
    {
      "id": "uuid",
      "name": "cpu_usage",
      "display_name": "CPU 使用率",
      "category": "system_resource",
      "collector": "panos_api",
      "interval": 60,
      "unit": "%",
      "data_type": "gauge",
      "chart_type": "line",
      "enabled": true,
      "builtin": true
    }
  ]
}
```

### POST /metrics/definitions
创建自定义指标（Admin）。

```json
{
  "name": "gp_active_users",
  "display_name": "GlobalProtect 在线用户数",
  "category": "vpn",
  "collector": "panos_api",
  "command": "<show><global-protect-gateway><current-user>",
  "parser": {
    "type": "xpath",
    "expr": "count(//entry)"
  },
  "interval": 60,
  "unit": "users",
  "data_type": "gauge",
  "chart_type": "line"
}
```

### PUT /metrics/definitions/{id}
修改指标配置（含采集频率）。

### DELETE /metrics/definitions/{id}
删除自定义指标（内置指标只能禁用，不能删）。

### PUT /metrics/definitions/{id}/interval
修改采集频率。

```json
{
  "interval": 120
}
```

---

## Metric Data 指标数据查询

### GET /metrics/data
查询指标时序数据。

**Query Params:**
- `device_id` — 设备 ID（必填）
- `metric_name` — 指标名称（必填）
- `start` — 起始时间 ISO8601
- `end` — 结束时间 ISO8601
- `granularity` — 聚合粒度秒数：`0`=原始, `300`=5min, `900`=15min, `3600`=1h, `86400`=1d
- `aggregation` — 聚合方式：avg/max/min/all（all 返回 avg+max+min）

**Response:**
```json
{
  "device_id": "uuid",
  "metric_name": "cpu_usage",
  "granularity": 300,
  "points": [
    {
      "timestamp": "2024-01-01T00:00:00Z",
      "avg": 45.2,
      "max": 67.8,
      "min": 32.1
    }
  ]
}
```

### GET /metrics/data/multi
多设备/多指标对比查询。

**Query Params:**
- `device_ids` — 逗号分隔
- `metric_names` — 逗号分隔
- `start`, `end`, `granularity`

---

## Alerts 告警模块

### GET /alerts/rules
获取告警规则列表。

### POST /alerts/rules
创建告警规则。

```json
{
  "name": "CPU 过高告警",
  "metric_name": "cpu_usage",
  "device_ids": ["uuid1", "uuid2"],
  "type": "threshold",
  "condition": {
    "operator": ">",
    "value": 80,
    "duration": 300
  },
  "severity": "warning",
  "notification_channels": ["feishu_group", "email_ops"],
  "enabled": true
}
```

告警类型（type）：
- `threshold` — 阈值告警
- `anomaly` — 异常检测
- `prediction` — 趋势预测

### PUT /alerts/rules/{id}
修改告警规则。

### DELETE /alerts/rules/{id}
删除告警规则。

### GET /alerts/events
获取告警事件历史。

**Query Params:**
- `severity` — critical/warning/info
- `status` — firing/resolved
- `device_id`
- `start`, `end`
- `page`, `page_size`

### POST /alerts/events/{id}/acknowledge
确认告警。

---

## Notification Channels 通知渠道

### GET /notifications/channels
获取通知渠道列表。

### POST /notifications/channels
创建通知渠道。

```json
{
  "name": "飞书运维群",
  "type": "feishu",
  "config": {
    "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"
  },
  "enabled": true
}
```

```json
{
  "name": "邮件通知",
  "type": "email",
  "config": {
    "smtp_host": "smtp.example.com",
    "smtp_port": 465,
    "username": "alert@example.com",
    "password": "***",
    "recipients": ["admin@example.com"]
  },
  "enabled": true
}
```

### POST /notifications/channels/{id}/test
测试通知渠道（发送测试消息）。

---

## Upload 数据上传

### POST /upload/acc
上传 ACC 导出数据。

**Request:** multipart/form-data
- `file` — CSV 文件
- `device_id` — 关联设备
- `data_type` — threat/traffic

**Response:**
```json
{
  "status": "success",
  "records_imported": 1523,
  "time_range": {
    "start": "2024-01-01T00:00:00Z",
    "end": "2024-01-07T23:59:59Z"
  }
}
```

---

## System 系统管理 (Admin)

### GET /system/settings
获取系统设置。

### PUT /system/settings
修改系统设置。

```json
{
  "retention_days": 365,
  "compress_after_days": 7,
  "max_query_points": 2000,
  "default_granularity_hints": {
    "2h": 0,
    "24h": 300,
    "7d": 900,
    "30d": 3600,
    "365d": 86400
  }
}
```

### GET /system/health
系统健康检查（采集状态、队列积压、磁盘用量）。

### GET /system/collectors
获取可用采集器插件列表。
