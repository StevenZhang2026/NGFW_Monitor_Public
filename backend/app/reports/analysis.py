"""Trend analysis and capacity prediction for report generation."""

from dataclasses import dataclass
import numpy as np


@dataclass
class TrendResult:
    avg: float
    max: float
    min: float
    current: float
    slope_per_hour: float
    slope_per_week: float
    change_pct: float | None  # vs previous period
    weeks_to_threshold: float | None  # None = not increasing or already above


def analyze_trend(
    values: list[float],
    timestamps_hours: list[float],
    threshold: float | None = None,
    prev_period_total: float | None = None,
) -> TrendResult:
    arr = np.array(values, dtype=float)
    t = np.array(timestamps_hours, dtype=float)

    avg = float(np.mean(arr))
    mx = float(np.max(arr))
    mn = float(np.min(arr))
    current = float(arr[-1]) if len(arr) > 0 else 0.0

    if len(arr) >= 2:
        coeffs = np.polyfit(t, arr, deg=1)
        slope_per_hour = float(coeffs[0])
    else:
        slope_per_hour = 0.0

    slope_per_week = slope_per_hour * 168

    change_pct = None
    if prev_period_total is not None and prev_period_total > 0:
        current_total = float(np.sum(arr))
        change_pct = round((current_total - prev_period_total) / prev_period_total * 100, 1)

    weeks_to_threshold = None
    if threshold is not None and slope_per_hour > 0 and current < threshold:
        hours_to = (threshold - current) / slope_per_hour
        weeks_to_threshold = round(hours_to / 168, 1)

    return TrendResult(
        avg=round(avg, 2),
        max=round(mx, 2),
        min=round(mn, 2),
        current=round(current, 2),
        slope_per_hour=round(slope_per_hour, 4),
        slope_per_week=round(slope_per_week, 2),
        change_pct=change_pct,
        weeks_to_threshold=weeks_to_threshold,
    )


@dataclass
class RankingItem:
    name: str
    value: float
    extra: dict


def compute_ranking(data: dict[str, float], extra_map: dict[str, dict] | None = None, top_n: int = 10) -> list[RankingItem]:
    sorted_items = sorted(data.items(), key=lambda x: x[1], reverse=True)[:top_n]
    results = []
    for name, value in sorted_items:
        extra = (extra_map or {}).get(name, {})
        results.append(RankingItem(name=name, value=round(value, 2), extra=extra))
    return results
