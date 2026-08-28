# 待办与优化路线图

已完成的功能与版本历史见 `CHANGELOG.md`,本文件只记未做的事。

## 未完成的功能

- Panorama 设备自动发现
- 数据保留策略自动执行（TimescaleDB retention policy）
- 多设备接入验证（PA-5500 / PA-7000 系列,接口命名与传感器布局不同）

## 待验证

- 报表邮件端到端验证（配置 SMTP → 自动发送 → 收件人收到 PDF）
- `cpu_usage` 解析修复后的真机验证（PA-440 上确认 `%Cpu(s)` 的 `id` 字段能匹配到），
  并复核 CPU 告警阈值——新读数含 sy/ni/wa，比修复前高
- `session_max` 的 `on_multiple`：多 DP 设备报的是每 DP 容量（sum）还是系统总量
  （first）待真机确认，在此之前它在 PA-5500/7000 上是硬失败

## 优化事项

- 数据保留策略自动执行
- 性能调优（采集间隔精细控制、worker 并发优化）
- Copilot 能力扩展（更多查询类型、多轮对话）
- 大设备接口白名单可配置（PA-5450/7050 逻辑接口多,全采会拉长采集耗时）

## 已知 bug

- `ha_state` 取的是 `.//group/local-info/state`,值是 `active`/`passive` 字符串,而单值
  解析器一律走 `float()`。配了 HA 的设备上这个指标只会产出 "Cannot parse value" 失败

## 安全

安全遗留项清单**不进版本控制**：逐条写明位置与利用路径的未修问题清单，对在跑这套系统
的人来说就是一份攻击清单，而本仓库有公开镜像。清单在 `security/private-findings.md`
（本机，`.gitignore`），修完任一项后跑 `bash scripts/security-gate.sh --update-baseline`
收缩 baseline。

已修的部分见 git 历史：凭据卫生、出网 TLS 校验、容器非 root、数据面端口只绑回环与
Postgres 口令必填、分组授权与凭据脱敏回写保护。
