"""
Format query results into natural language / markdown for the user.
"""


def format_bytes(b: float) -> str:
    if b >= 1e9:
        return f"{b / 1e9:.1f} GB"
    if b >= 1e6:
        return f"{b / 1e6:.1f} MB"
    if b >= 1e3:
        return f"{b / 1e3:.1f} KB"
    return f"{b:.0f} B"


def format_response(action: str, params: dict, result: dict, summary_request: str) -> str:
    if action == "acc_ranking":
        return _format_ranking(params, result, summary_request)
    elif action == "acc_trend":
        return _format_trend(params, result, summary_request)
    elif action == "metric_data":
        return _format_metric(params, result, summary_request)
    elif action == "alert_events":
        return _format_alerts(params, result, summary_request)
    elif action == "device_status":
        return _format_devices(result, summary_request)
    return "暂不支持该查询类型。"


def _format_ranking(params: dict, result: dict, summary: str) -> str:
    items = result.get("items", [])
    if not items:
        return f"查询结果：{summary}\n\n暂无数据。"

    is_app = params.get("metric_name") == "acc_application"
    header = "应用" if is_app else "威胁"
    lines = [f"**{summary}**\n"]
    lines.append(f"| # | {header}名称 | {'流量' if is_app else '次数'} |")
    lines.append("|---|---|---|")

    for i, item in enumerate(items, 1):
        name = item.get("name", "unknown")
        if is_app:
            val = format_bytes(item.get("bytes", 0))
        else:
            val = f"{item.get('count', 0)} 次"
        lines.append(f"| {i} | {name} | {val} |")

    return "\n".join(lines)


def _format_trend(params: dict, result: dict, summary: str) -> str:
    items = result.get("items", [])
    if not items:
        return f"查询结果：{summary}\n\n暂无数据。"

    lines = [f"**{summary}**\n"]
    lines.append(f"时间粒度：{result.get('bucket', 'N/A')}")
    lines.append(f"包含 {len(items)} 个项目：{', '.join(items[:5])}{'...' if len(items) > 5 else ''}")
    lines.append("\n请查看 ACC 数据页面的趋势图获取详细可视化。")
    return "\n".join(lines)


def _format_metric(params: dict, result: dict, summary: str) -> str:
    points = result.get("points", [])
    if not points:
        return f"查询结果：{summary}\n\n暂无数据。"

    values = [p.get("avg") or p.get("value", 0) for p in points]
    avg_val = sum(values) / len(values) if values else 0
    max_val = max(values) if values else 0
    min_val = min(values) if values else 0

    metric = params.get("metric_name", "")
    # The unit comes from the metric definition, not a hardcoded list — a metric
    # added through the Web UI has one too, and a counter's unit describes the
    # rate the query layer derived, not the stored counter.
    unit = result.get("unit", "")

    lines = [f"**{summary}**\n"]
    lines.append(f"- 数据点数：{len(points)}")
    lines.append(f"- 平均值：{avg_val:.1f}{unit}")
    lines.append(f"- 最大值：{max_val:.1f}{unit}")
    lines.append(f"- 最小值：{min_val:.1f}{unit}")
    if result.get("derived") == "rate":
        lines.append(
            "\n（该指标在设备上是累计计数器，以上是按相邻采样点差分得到的速率，"
            "取各接口中最繁忙的一条。设备整机吞吐量请查 session_kbps。）"
        )

    if metric == "cpu_usage" and max_val > 80:
        lines.append(f"\n⚠️ CPU 峰值达到 {max_val:.1f}%，建议关注。")
    return "\n".join(lines)


def _format_alerts(params: dict, result: dict, summary: str) -> str:
    items = result.get("items", [])
    lines = [f"**{summary}**\n"]

    if not items:
        lines.append("当前无匹配的告警事件。")
        return "\n".join(lines)

    lines.append(f"共 {len(items)} 条告警：\n")
    lines.append("| 时间 | 级别 | 指标 | 状态 | 值 |")
    lines.append("|---|---|---|---|---|")

    for item in items[:20]:
        ts = item.get("triggered_at", "")[:16]
        sev = item.get("severity", "")
        metric = item.get("metric_name", "")
        status = "🔴 活跃" if item.get("status") == "firing" else "✅ 已确认"
        val = item.get("value", "")
        lines.append(f"| {ts} | {sev} | {metric} | {status} | {val} |")

    if len(items) > 20:
        lines.append(f"\n...还有 {len(items) - 20} 条未显示。")
    return "\n".join(lines)


def _format_devices(result: dict, summary: str) -> str:
    items = result.get("items", [])
    lines = [f"**{summary}**\n"]

    if not items:
        lines.append("暂无设备。")
        return "\n".join(lines)

    online = sum(1 for d in items if d.get("status") == "online")
    lines.append(f"- 设备总数：{len(items)}")
    lines.append(f"- 在线：{online}")
    lines.append(f"- 离线：{len(items) - online}\n")
    lines.append("| 设备名 | IP | 状态 |")
    lines.append("|---|---|---|")

    for d in items:
        status = "🟢 在线" if d.get("status") == "online" else "🔴 离线"
        lines.append(f"| {d.get('name', '')} | {d.get('hostname', '')} | {status} |")

    return "\n".join(lines)
