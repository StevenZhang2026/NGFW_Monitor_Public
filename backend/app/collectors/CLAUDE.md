# 采集器插件 — 踩坑记录

本文件在读取 `backend/app/collectors/` 下文件时按需加载,不占用常驻上下文。
改 ACC / 报表采集前必读。

## PAN-OS 报表 API（ACC 数据）

- **报表读哪个库决定数字对不对**：`top-applications-summary` 读 `appstat`（App-ID 扫描统计），不是 ACC 界面 Application Usage 的来源，实测同一小时 253MB vs `trsum` 1407MB。应用流量必须走 `trsum` 的内联自定义报表（`reportname=custom-dynamic-report` + `cmd=<type><trsum>…`）；威胁走 `top-attacks-acc`，它本来就读 `thsum`，是对的
- 必须 `reporttype=dynamic`，**不能 `predefined`**：predefined 是设备每天预生成的批次，会静默忽略 `period`，永远返回前一整天的快照
- 三种**静默失效**（设备返回 success 但 0 行，与空桶无法区分）：`custom-dynamic-report` 忽略 URL 上的 `start-time`/`end-time`（窗口必须写进 `cmd`）；`trsum` 的 `values` 加 `packets`；`thsum` 的值字段写 `threats`（正确是 `count`）
- `query` 只在 `start-time`/`end-time` 窗口**内**过滤，不能用来定义窗口。窗口是设备本地时间，`end-time` 含端点，所以桶尾要减 1 秒
- 不要把 `top-spyware-threats-summary` / `top-spyware-download-summary` 与 `top-attacks-acc` 合并采集——返回相同行，会把 spyware 重复计数
- 严重性过滤 pass 是总报表的**严格子集，count 逐字节相同**，所以 `_merge` 跨报表用 `max` 而不是求和（求和会把重叠行翻倍）；单个报表内部仍求和
- 威胁排名按次数排序 + topn 截断，罕见但危险的事件会被高频噪声挤掉，所以 critical / high 各跑一次 `query=(severity eq …)` 独占配额保证可见；medium 及以下仍受挤压
- 威胁按 `tid` 做存储键——不同 tid 会共用同一个显示名，按名字做键会撞主键。部分 spyware/DNS 威胁设备本身没有名字，`threatid` 直接返回数字 ID
- 设备时区从 `show clock` 推导，不能硬编码（CST 既是中国也是美国中部）
- v2.2 之前的 ACC 历史数据走 Log Query API，有 `nlogs` 上限，流量大的小时截断越狠（实测某小时 81MB vs 实际 681MB），跨 v2.2 切换点的环比和趋势斜率不可比
