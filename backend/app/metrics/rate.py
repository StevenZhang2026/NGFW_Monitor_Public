"""Read-time conversion of cumulative counters into rates.

PAN-OS reports interface traffic as a monotonically increasing byte counter, and
that is what gets stored — raw data is kept exactly as the device reported it
(design constraint 2). Differencing therefore happens at read time, where it can
be corrected or reinterpreted without a backfill, and where the stored counter
is still available for anyone who wants it.

Shared by the metrics API and the Copilot query layer so both report the same
number for the same question.
"""

# Bound on how far before the requested start a counter query looks for a
# predecessor. A rate needs the point *before* the first one in range, or a chart
# loses its leading sample every time the range shifts.
MAX_RATE_LOOKBACK = 3600


def counter_rate_config(definition) -> tuple[bool, float, int]:
    """(is_counter, scale, lookback_seconds) for a metric definition.

    `scale` converts the stored unit per second into the definition's declared
    `unit` — 0.008 turns bytes/s into kbps. It lives in `parser.rate` because the
    schema is created with create_all and has no migration tooling for a new
    column.
    """
    if definition is None:
        return False, 1.0, MAX_RATE_LOOKBACK

    data_type = getattr(definition.data_type, "value", definition.data_type)
    if data_type != "counter":
        return False, 1.0, MAX_RATE_LOOKBACK

    cfg = (definition.parser or {}).get("rate") or {}
    scale = float(cfg.get("scale", 1.0))
    lookback = min(2 * (definition.interval or 60), MAX_RATE_LOOKBACK)
    return True, scale, lookback


def counter_rate_source(
    device_condition: str, name_condition: str, lookback: int, scale: float
) -> str:
    """SQL yielding (timestamp, device_id, mn, value) with value as a rate.

    `device_condition` and `name_condition` are SQL fragments supplied by the
    caller (`device_id = :device_id`, `device_id = ANY(:device_ids)`, `TRUE`, …);
    `:start` and `:end` are always required binds.

    Differencing partitions by device *and* instance: every interface keeps its
    own counter, and two devices' counters have nothing to do with each other, so
    a partition that missed either dimension would subtract unrelated values.

    A negative delta means the counter went backwards — the device rebooted or
    the counter wrapped. There is no way to know how much traffic crossed that
    discontinuity, so the point is dropped rather than turned into an invented
    spike or a negative rate.
    """
    return f"""
        WITH windowed AS (
            SELECT timestamp, device_id, metric_name AS mn, value
            FROM metric_data
            WHERE {device_condition} AND {name_condition}
              AND timestamp >= CAST(:start AS timestamptz)
                               - INTERVAL '{int(lookback)} seconds'
              AND timestamp <= :end
        ),
        diffed AS (
            SELECT timestamp, device_id, mn, value,
                   lag(value) OVER w AS prev_value,
                   lag(timestamp) OVER w AS prev_ts
            FROM windowed
            WINDOW w AS (PARTITION BY device_id, mn ORDER BY timestamp)
        )
        SELECT timestamp, device_id, mn,
               (value - prev_value)
                   / EXTRACT(epoch FROM (timestamp - prev_ts)) * {scale} AS value
        FROM diffed
        WHERE prev_ts IS NOT NULL
          AND timestamp >= :start
          AND timestamp > prev_ts
          AND value >= prev_value
    """
