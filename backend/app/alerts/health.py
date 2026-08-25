"""Alerting on the collection pipeline itself falling behind.

Every other alert watches the firewall. This one watches the monitor, because
the monitor's failures are the quiet ones: a metric that stopped being collected
looks exactly like a metric that has been flat, and a collection cycle dropped
because the previous one had not finished looks exactly like a gap in a chart.
Design constraint 5 forbids exactly this — when there is not enough capacity to
collect at the configured frequency, the admin has to be told, so they can decide
between adding resources and lowering the frequency. Nothing here ever adjusts
the frequency itself.

`memory_usage` is the worked example: its parser stopped matching a PAN-OS
output change and produced nothing for four days without one warning anywhere.

The signals, ordered from earliest warning to hardest failure:

  collect.interval_unreachable  a metric is configured faster than the scheduler
                                dispatches, so its interval can never be honoured
  collect.overrun               a device's collection is eating most of its
                                interval — nothing lost yet, but no headroom left
  collect.queue_backlog         tasks queue faster than the workers drain them
  collect.skipped               a cycle was skipped because the previous one was
                                still running; that cycle's data does not exist
  <metric name>                 a specific metric has stopped producing points
  collect.device_offline        every collector failed against the device

The first three are warnings — capacity is shrinking. The last three are
critical — data is already missing. That split is derived rather than
configured: "余量在变小" and "数据已经丢了" are different in kind, and
collapsing them onto one admin-chosen level would throw the distinction away.
The admin's severity choice applies to the warning tier, so noisy headroom
warnings can be turned down to info without also hiding data loss.

Findings hang off the builtin "采集健康度" rule, so channels, cooldown and
enable/disable are configured in the same UI as every other alert instead of
through a second parallel mechanism.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from app.collectors.panos_report import bucket_marker_name, bucket_seconds, target_bucket
from app.config import settings
from app.models.alert import Severity
from app.tasks.locks import collect_durations, queue_depth, take_skip_deltas

# Identifies the builtin rule. AlertType cannot gain a `collection_health`
# member: the schema is built with create_all, which will not ALTER an existing
# postgres enum, so an added value would exist in code and not in the database.
# The rule is stored as `threshold` and skipped by the threshold handler, which
# keys off this metric name.
HEALTH_RULE_METRIC = "__collection_health__"
HEALTH_RULE_NAME = "采集健康度"

# Signals with no single metric or no single device behind them.
SYSTEM_DEVICE_ID = "system"
SYSTEM_DEVICE_NAME = "系统"
SIGNAL_DEVICE_OFFLINE = "collect.device_offline"
SIGNAL_OVERRUN = "collect.overrun"
SIGNAL_SKIPPED = "collect.skipped"
SIGNAL_QUEUE_BACKLOG = "collect.queue_backlog"
SIGNAL_INTERVAL_UNREACHABLE = "collect.interval_unreachable"

# Collectors the beat scheduler actually polls. Mirrors app.tasks.collect —
# a `file_upload` metric has no schedule, so it can never be "late".
POLLED_COLLECTORS = ("panos_api", "panos_ssh")
REPORT_COLLECTOR = "panos_report"

_MARKER_PREFIX = bucket_marker_name("")

DEFAULT_CONDITION = {
    # Consecutive missed cycles before a metric counts as stopped. Two is within
    # normal jitter; three means something is broken rather than slow.
    "stale_multiplier": 3,
    # Fraction of a device's collection budget that counts as "no headroom".
    "overrun_ratio": 0.7,
    # Skipped cycles within one check window before reporting.
    "skip_threshold": 1,
    # Queue depth is compared against the device count, but a handful of tasks is
    # never a backlog on a small deployment, so the comparison has a floor.
    "backlog_floor": 5,
    # How far back to look for a metric's newest point. Bounded so the query
    # does not scan every chunk of the hypertable.
    "stale_lookback_days": 30,
}


@dataclass
class Finding:
    device_id: str
    device_name: str
    metric_name: str
    severity: Severity
    message: str
    value: str | None = None

    @property
    def key(self) -> tuple[str, str]:
        """Identity of the problem, so one problem yields one open event."""
        return (self.device_id, self.metric_name)


def _human(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}秒"
    if seconds < 3600:
        return f"{seconds // 60}分{seconds % 60}秒"
    if seconds < 86400:
        return f"{seconds // 3600}小时{seconds % 3600 // 60}分"
    return f"{seconds // 86400}天{seconds % 86400 // 3600}小时"


def _cycle_budget(metrics) -> int:
    """Seconds a device's collection may take before data starts going missing.

    A collection only has to finish before the *next* one that will actually
    poll something, which is the shortest configured interval — but never sooner
    than the scheduler can dispatch, so the beat interval is the floor.
    """
    intervals = [m.interval or 60 for m in metrics if m.collector in POLLED_COLLECTORS]
    if not intervals:
        return settings.collect_beat_interval
    return max(min(intervals), settings.collect_beat_interval)


async def evaluate_collection_health(session, rule, devices, metrics) -> list[Finding]:
    """All the ways collection is currently behind, as alertable findings."""
    condition = {**DEFAULT_CONDITION, **(rule.condition or {})}
    warn = rule.severity or Severity.warning
    budget = _cycle_budget(metrics)

    findings: list[Finding] = []
    findings += _offline_findings(devices)
    findings += await _stale_findings(session, devices, metrics, condition)
    findings += _overrun_findings(devices, budget, condition, warn)
    findings += _skip_findings(devices, budget, condition)
    findings += _backlog_findings(len(devices), condition, warn)
    findings += _unreachable_interval_findings(metrics, warn)
    return findings


def _offline_findings(devices) -> list[Finding]:
    from app.models.device import DeviceStatus

    out = []
    for device in devices:
        if device.status != DeviceStatus.offline:
            continue
        out.append(Finding(
            device_id=device.id,
            device_name=device.name,
            metric_name=SIGNAL_DEVICE_OFFLINE,
            severity=Severity.critical,
            message=(
                f"设备 {device.name}（{device.hostname}）采集全部失败，已标记离线。"
                f"最近一次成功采集：{device.last_seen or '无记录'}。"
                "该设备当前所有指标都在丢数据。"
            ),
            value="offline",
        ))
    return out


async def _stale_findings(session, devices, metrics, condition) -> list[Finding]:
    """Metrics that used to produce points on a device and stopped.

    Only regressions are reported. A metric with no point ever on this device is
    left alone on purpose: a freshly added device has none yet, and some metrics
    legitimately never resolve on some platforms — `ha_state` matches nothing on
    a standalone PA-440. Those are configuration facts visible where the metric
    is configured, not collection falling behind, and alerting on them would
    make the signal permanent noise.
    """
    from sqlalchemy import text

    if not devices or not metrics:
        return []

    lookback_days = int(condition["stale_lookback_days"])
    multiplier = float(condition["stale_multiplier"])

    # Grouped on the stored name rather than its base, because `_bucket::<metric>`
    # ACC markers would otherwise all collapse onto one base of `_bucket`.
    rows = (await session.execute(
        text(f"""
            SELECT device_id, metric_name, MAX(timestamp) AS last_ts
            FROM metric_data
            WHERE device_id = ANY(:device_ids)
              AND timestamp > now() - INTERVAL '{lookback_days} days'
            GROUP BY device_id, metric_name
        """),
        {"device_ids": [d.id for d in devices]},
    )).fetchall()

    last_seen: dict[tuple[str, str], datetime] = {}
    for row in rows:
        name = row.metric_name
        key = name if name.startswith(_MARKER_PREFIX) else name.split("::")[0]
        last = row.last_ts
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        current = last_seen.get((row.device_id, key))
        if current is None or last > current:
            last_seen[(row.device_id, key)] = last

    now = datetime.now(timezone.utc)
    out = []
    for device in devices:
        for metric in metrics:
            if metric.collector in POLLED_COLLECTORS:
                last = last_seen.get((device.id, metric.name))
                if last is None:
                    continue
                interval = metric.interval or 60
                age = (now - last).total_seconds()
                missed = int(age // interval)
                if missed < multiplier:
                    continue
                out.append(Finding(
                    device_id=device.id,
                    device_name=device.name,
                    metric_name=metric.name,
                    severity=Severity.critical,
                    message=(
                        f"{device.name} 的「{metric.display_name}」已 {_human(age)} 没有新数据点，"
                        f"采集间隔 {interval}s，相当于连续错过 {missed} 个周期。"
                        "设备仍在响应其他指标，通常是该指标的命令输出变了或解析规则不再匹配。"
                    ),
                    value=f"{_human(age)}",
                ))
            elif metric.collector == REPORT_COLLECTOR:
                # ACC buckets with no traffic write no data rows, so the marker
                # row is the only honest evidence that a bucket was collected.
                marker = last_seen.get((device.id, bucket_marker_name(metric.name)))
                if marker is None:
                    continue
                size = bucket_seconds(metric)
                latest_bucket, _ = target_bucket(metric)
                behind = int((latest_bucket - marker).total_seconds() // size)
                if behind < multiplier:
                    continue
                out.append(Finding(
                    device_id=device.id,
                    device_name=device.name,
                    metric_name=metric.name,
                    severity=Severity.critical,
                    message=(
                        f"{device.name} 的「{metric.display_name}」已落后 {behind} 个"
                        f"{size // 60} 分钟聚合桶，最后采到的桶是 "
                        f"{marker.strftime('%Y-%m-%d %H:%M')} UTC。"
                    ),
                    value=f"落后{behind}个桶",
                ))
    return out


def _overrun_findings(devices, budget: int, condition, warn: Severity) -> list[Finding]:
    """Devices whose collection is using up most of the time it has.

    A leading indicator: nothing is lost yet. It exists so the admin hears about
    shrinking headroom before the pipeline starts dropping cycles.
    """
    durations = collect_durations()
    ratio = float(condition["overrun_ratio"])
    now = datetime.now(timezone.utc).timestamp()

    out = []
    for device in devices:
        stat = durations.get(device.id) or {}
        last = stat.get("last")
        if last is None:
            continue
        # A recorded duration from a device that is no longer being collected
        # says nothing about now; staleness and skips cover that case.
        recorded_at = stat.get("at")
        if recorded_at is not None and now - recorded_at > 3 * budget:
            continue
        if last < budget * ratio:
            continue
        peak = stat.get("max", last)
        out.append(Finding(
            device_id=device.id,
            device_name=device.name,
            metric_name=SIGNAL_OVERRUN,
            severity=warn,
            message=(
                f"{device.name} 上一次采集耗时 {last:.1f}s，占用采集周期 {budget}s 的 "
                f"{last / budget * 100:.0f}%（历史峰值 {peak:.1f}s）。"
                "余量已经很小，继续增加指标或设备会开始丢采集周期，"
                "需要扩容 worker、放宽采集间隔，或减少该设备的指标数量。"
            ),
            value=f"{last:.1f}s/{budget}s",
        ))
    return out


def _skip_findings(devices, budget: int, condition) -> list[Finding]:
    """Cycles that were skipped because the previous one was still running.

    Reading the deltas consumes them, so a skip is reported once and the event
    resolves on the next check if it does not recur — it is an incident, not a
    state. Skips for devices outside this rule's scope are consumed and dropped;
    the rule owns the whole tally or none of it.

    A skipped tick where nothing happened to be due loses nothing, and this does
    not try to tell the two apart. With every interval at or above the beat
    interval the distinction does not arise, and over-reporting is the correct
    direction to be wrong about missing data.
    """
    threshold = int(condition["skip_threshold"])
    known = {d.id: d for d in devices}

    out = []
    for device_id, count in take_skip_deltas().items():
        device = known.get(device_id)
        if device is None or count < threshold:
            continue
        out.append(Finding(
            device_id=device_id,
            device_name=device.name,
            metric_name=SIGNAL_SKIPPED,
            severity=Severity.critical,
            message=(
                f"{device.name} 有 {count} 个采集周期被跳过：上一轮采集还没结束，"
                f"下一轮就到了（采集周期 {budget}s）。这些周期的数据点不存在，"
                "且不会补采。"
            ),
            value=f"{count}次",
        ))
    return out


def _backlog_findings(device_count: int, condition, warn: Severity) -> list[Finding]:
    """Tasks piling up faster than the workers drain them.

    A queued collection task carries `expires`, so a backlog does not just delay
    collection — the superseded tasks are discarded and their cycles are lost.
    """
    depth = queue_depth()
    if depth is None:
        return []

    floor = max(device_count, int(condition["backlog_floor"]))
    if depth <= floor:
        return []

    severe = depth > 2 * floor
    return [Finding(
        device_id=SYSTEM_DEVICE_ID,
        device_name=SYSTEM_DEVICE_NAME,
        metric_name=SIGNAL_QUEUE_BACKLOG,
        severity=Severity.critical if severe else warn,
        message=(
            f"任务队列积压 {depth} 个任务（{device_count} 台设备，并发 "
            f"{settings.collector_concurrency}）。"
            + (
                f"排队时间已经超过任务有效期 {settings.collect_task_expires}s，"
                "过期任务会被直接丢弃，对应周期的数据不会产生。"
                if severe else
                "worker 消化速度已经跟不上派发速度，继续恶化就会开始丢周期。"
            )
            + "（队列深度只统计仍在 Redis 中的任务，worker 预取的部分不可见，实际积压可能更多。）"
        ),
        value=f"{depth}",
    )]


def _unreachable_interval_findings(metrics, warn: Severity) -> list[Finding]:
    """Metrics configured faster than the scheduler can dispatch.

    The admin owns the interval (design constraint 1) and the system will not
    quietly change it — but it also must not pretend to honour a frequency it
    cannot deliver.
    """
    beat = settings.collect_beat_interval
    out = []
    for metric in metrics:
        if metric.collector not in POLLED_COLLECTORS:
            continue
        interval = metric.interval or 60
        if interval >= beat:
            continue
        out.append(Finding(
            device_id=SYSTEM_DEVICE_ID,
            device_name=SYSTEM_DEVICE_NAME,
            metric_name=metric.name,
            severity=warn,
            message=(
                f"「{metric.display_name}」配置的采集间隔是 {interval}s，"
                f"但采集任务每 {beat}s 才派发一次，实际最快只能 {beat}s 采一次。"
                f"请把间隔调整到 {beat}s 或以上，或调小 COLLECT_BEAT_INTERVAL。"
            ),
            value=f"{interval}s<{beat}s",
        ))
    return out
