# 更新日志

本项目版本号遵循 `主版本.次版本.修订号`。标签打在对应发布提交上，`git tag -n99` 可看每个标签的完整说明。

## v2.2 — 采集正确性与可观测性

ACC 采集从原始日志查询改为设备侧聚合，采集成本与日志量脱钩；补上采集链路自身的监控；修掉三个会静默给出错误数字的问题。

### 新增

- **ACC 采集改为设备侧聚合**：由防火墙的汇总库直接返回排名结果，不再拉原始日志。PA-5450 一小时几十万条日志和 PA-440 几百条的采集开销相同。窗口对齐到设备自身的 15 分钟颗粒度，桶是幂等的，可回补历史
- **保证 Critical / High 威胁可见**：威胁排名按次数排序 + topn 截断，罕见但危险的事件会被高频噪声挤掉（实测 3 条 low 共 7173 次挤掉了 10 条 medium，含只出现 1 次的 Malicious Windows Executable）。critical / high 各跑一次独立的严重性过滤，独占 topn 配额
- **采集链路自检告警**：六个信号（停采 / 采集耗时逼近周期 / 采集周期被跳过 / 队列积压 / 采集间隔无法满足 / 设备离线），每 120s 评估，事件去重 + 自动恢复，与指标告警共用通知渠道和冷却
- **采集防重入**：per-device Redis 锁，上一轮还没采完就跳过本轮，而不是并发采同一台设备
- `GET /api/v1/alerts/collection-health` — 采集链路原始体征，用于诊断自检告警

### 修复

- **ACC 应用流量读错了数据库**：`top-applications-summary` 读的是 `appstat`（App-ID 扫描统计），不是 ACC 界面 Application Usage 的来源。实测 PA-440 同一小时 appstat 253MB vs `trsum` 1407MB，另一小时 2.5MB vs 590MB。改为内联自定义动态报表读 `trsum`。威胁不受影响（`top-attacks-acc` 本来就读 `thsum`）
- **通知冷却把每一条真实告警都静音了**：`session.add(event)` 之后在同一 session 里 `SELECT COUNT` 会把待写入的这行 flush 出去并数进结果，冷却判定永远认为刚发过。事件照样入库，就是没人收到通知。冷却判定移到 `session.add` 之前。注意通知渠道的「测试发送」按钮绕过冷却和事件写入，验证的是渠道配置而非告警链路
- **累计计数器被当成瞬时值展示**：接口收发字节数是单调递增的累计值，存储不变，改在查询层按 `lag()` 差分为速率。差分为负说明设备重启或计数器回绕，该点丢弃
- **采集命令重复下发**：多个指标共用一条命令（`show session info` 喂 4 个指标，`show system resources` 喂 2 个），原来每个指标各问一次。按命令去重后单次采集 19.9s → 9.5s；SSH 每条命令固定 4s settle + 最多 8s 排空，重复命令是秒级浪费
- 指标 `interval` 之前不生效，实际按 beat 周期采集；现在管理员设的频率才是真的生效频率
- `worker_prefetch_multiplier=1`：worker 预取的任务在队列深度里看不见，积压会藏在 worker 内存里，还会在里面熬过 `expires` 被丢掉

## v2.1 — AI Copilot 与告警优化

- **AI Copilot 助手**：自然语言查询（"最近 3 天威胁 Top 10"），LLM 意图解析 + 模板格式化，模型可配置
- **告警体系优化**：通知冷却、活跃告警计数、批量确认
- **ACC 图表修复**：趋势图 tooltip 时间轴对齐，趋势图与饼图颜色统一
- 交互式系统架构图和 AI Copilot 数据流图

## v2.0 — 报表模块

- **报表模块**：周报/月报自动生成 PDF，趋势分析 + 容量预测，邮件推送，Web 端管理模板和历史
- **ACC 实时采集重构**：Log Query API 替代 Report API，时间戳对齐整点
- **安装工具套件**：`install.sh` / `upgrade.sh` / `uninstall.sh` / `status.sh` + INSTALL.md
- **权限体系**：用户管理 CRUD、角色分配、设备分组与 Scope 权限过滤
- **ACC 数据可视化**：应用流量与威胁排名、趋势图、饼图，支持 API 采集 + CSV 导入
- 设备状态自动检测（采集失败→offline，采集成功→online）
- 安全修复：SQL 注入、登录限速、Scope 越权、角色校验

## v1.1 — 通知渠道修复

- 飞书 webhook 始终返回 HTTP 200，改为检查响应体 `code` 字段判断实际成功
- `verify=False` 解决企业网络 SSL inspection 代理证书问题
- 消息模板加入「防火墙」关键词以匹配飞书机器人安全校验
- 通知器返回 `SendResult` 携带错误详情，前端展示具体失败原因

## v1.0 — 端到端监控平台

- 后端 FastAPI + Celery + TimescaleDB，per-device 批量采集，连接复用（每周期单 HTTPS + SSH 会话）
- 前端 React + Ant Design + ECharts，设备/告警/指标完整 CRUD
- 10 个内置指标（CPU、内存、会话、温度、接口、HA）
- Web UI 配置自定义指标（命令 + 解析规则）
- 告警引擎（threshold / anomaly / prediction）+ 飞书/企业微信/邮件通知
- HTTPS 自签名证书，Docker Compose 部署
