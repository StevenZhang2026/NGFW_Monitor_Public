# 更新日志

本项目版本号遵循 `主版本.次版本.修订号`。标签打在对应发布提交上，`git tag -n99` 可看每个标签的完整说明。

## v3.0 — 安全加固与门禁自动化

主线是把「能跑」的系统收拾到能交付：凭据卫生、出网 TLS、容器非 root、数据面端口回环、分组授权补齐，并把安全关卡从「记得跑」变成 CI 自动触发。另有两条独立功能线（告警事件服务端分页、设备离线轻量探测与 ACC 回补）。

### 升级注意

- **BREAKING：`POSTGRES_PASSWORD` 改为必填**（`${VAR:?}`，不再回落到 `changeme`）。`.env` 里缺这一项的部署会直接报错退出。默认回落会让忘配的安装静默用上公开已知的口令
- 容器改非 root 后 nginx 监听端口改到 8080/8443，compose 的宿主映射已同步；`upgrade.sh` 会幂等 chown 数据卷
- 后端 8000 / Postgres 5432 / Redis 6379 不再对 LAN 发布，跨主机访问走 SSH 隧道

### 安全加固

- **清理历史凭据泄露，加 gitleaks 提交门禁**：删掉会持续累积明文口令 / API Key / JWT 的开发对话导出，删掉孤儿 `env.example`（里面填的是当时线上真实在用的管理员口令），`install.sh` 补上从来没写过的 `JWT_SECRET_KEY`（等于一直用公开已知的 `change-me` 签 JWT）。泄露的口令均已轮换 —— 凭据进过 git 历史，删文件无效。`.gitleaks.toml` 补三条自定义规则：默认规则是熵驱动 + 已知格式驱动，10 字符的人类口令和 PAN-OS API Key（`LUFRPT` 前缀）两类都不报
- **出网请求恢复 TLS 校验**：飞书/企微 webhook 和 AI 模型请求的 header 或 URL 里带着凭据，`verify=False` 等于交给链路上任意中间人。出网侧统一走 `app/outbound.py` 默认校验；设备侧（管理网自签名证书）是另一条链路、开关独立，保持不校验
- **容器改非 root 运行**：后端/worker/beat/前端切到镜像里写死的 uid（不能让系统随机分配 —— 命名卷属主继承自首次创建，uid 一变存量卷就变只读）。celery beat 的 schedule 挪到 `/tmp` 而不是把 `/app` 整体 chown（那样代码目录可写，RCE 能落地持久化）
- **数据面端口只绑回环**：`ports: "5432:5432"` 是发布到 `0.0.0.0`、绕过宿主防火墙，实测 LAN 内可直连本项目的 Postgres、Redis 和后端 8000。Redis 同时是 Celery broker 且没设 `requirepass`，暴露 6379 等于 LAN 内任意主机可投递任务让 worker 执行
- **补齐分组授权与凭据脱敏回写保护**：人工审计发现四处 scope 缺失 —— `/metrics/data` 完全没校验 `device_id`；acc-trend / acc-ranking 省略 `device_id` 时不加过滤（受限用户直接拿到全设备聚合，连 UUID 都不用猜）；Copilot 5 个 action 只有 1 个过了 scope；批量确认的过滤只写在一条 else 分支上。新增 `scoped_device_sql()` 区分「全局」与「范围内全部」，空 scope fail-closed。脱敏白名单扩到 `webhook_url` / `token` / `api_key`（webhook URL 本身就是 bearer 型凭据），并同时做回写保护：约定掩码值 = 保持不变

### 门禁与 CI

- **发布前安全关卡** `scripts/security-gate.sh`：串起 gitleaks / bandit / trivy / semgrep / pip-audit / npm audit，确定性、不用 LLM，只报相对 `security/*.json` baseline 的新增。全量报警的关卡第一次就是红的，两周内就会被绕过或删掉
- **关卡挂到 GitHub Actions**：之前它只是文档里的一行命令，没有任何 hook 或 CI 调用。触发为 push main / tag `v*` / PR / 手动；`fetch-depth: 0`（关卡第一项扫全 git 历史，浅克隆会静默只扫最新 commit）；失败时把 `/tmp/gate-*.log` 打进日志，否则 runner 销毁后线索就没了
- **凭据门禁的 hook 本体进版本控制**：改用 `core.hooksPath` 指向仓库内的 `scripts/githooks/`，hook 变成受版本控制、模式 100755 的普通文件，逻辑改动出现在 diff 里，不再由安装脚本生成到 `.git/hooks`
- 关卡的 semgrep 去掉 `--quiet`：它只让成功时的日志干净一点，代价是拉不到规则库时日志整个是空的，CI 里只剩一句没有下文的 FAIL

### 新增

- **告警事件服务端分页**：前端原来一次性拉全表做前端分页，页数被单次请求条数截死，看起来永远只有 3 页。接口改回过滤后的 `total`；「全部确认」的按钮状态改读全局活跃数，不再从当前页推断
- **设备离线后只做轻量可达性探测，恢复后回补 ACC 桶**：离线设备原来仍按指标逐个采集，每个指标各付一次完整连接超时，还把一次设备故障放大成每个指标一条 critical 告警。改为每周期一次短探测，通了才恢复正常采集；离线期间漏掉的 ACC 桶恢复后回补，两端有界（每周期桶数上限 + 不追指定小时数以外的历史）
- 告警列表消息列不再截断：自检告警的消息本身含处置说明，ellipsis 截掉后半句等于把结论截掉。其余列定宽，剩余宽度全给消息列并自动换行

### 文档

- CLAUDE.md 顶部新增通用 AI 编码行为规约；删掉与 CHANGELOG / git tag 重复且必然过期的进度清单，待办移到 `docs/roadmap.md`，ACC 报表 API 的坑移到 `backend/app/collectors/CLAUDE.md`（按需加载）；新增「分组授权」小节，并记下越权只能靠 diff 审查发现 —— 关卡和扫描器对授权缺陷是零覆盖
- 安全遗留项清单**不进版本控制**：逐条写明位置与利用路径的未修问题清单，对在跑这套系统的人就是一份攻击清单，而本仓库有公开镜像。清单落在 `security/private-findings.md`（已 gitignore），roadmap 只留指针
- `api-spec.md` 记可观测的行为变化：范围外 403 / 事件 404、事件列表返回 `total`、通知渠道 config 的凭据字段回显 `***` 且提交 `***` 表示保持不变

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
