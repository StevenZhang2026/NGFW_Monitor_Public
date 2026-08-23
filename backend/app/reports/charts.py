"""Server-side chart rendering with matplotlib → PNG bytes."""

import io
import base64
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np


plt.rcParams["font.sans-serif"] = ["WenQuanYi Zen Hei", "SimHei", "DejaVu Sans", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False


def render_trend_chart(
    timestamps: list[datetime],
    values: list[float],
    title: str,
    ylabel: str,
    slope_per_hour: float = 0.0,
    threshold: float | None = None,
    predict_weeks: int = 4,
) -> str:
    """Render a trend line chart with optional prediction. Returns base64 PNG."""
    fig, ax = plt.subplots(figsize=(8, 3.5), dpi=120)

    ax.plot(timestamps, values, color="#1677ff", linewidth=1.5, label="实际值")
    ax.fill_between(timestamps, values, alpha=0.1, color="#1677ff")

    if slope_per_hour > 0 and len(timestamps) >= 2:
        last_t = timestamps[-1]
        last_v = values[-1]
        predict_hours = predict_weeks * 168
        future_ts = [last_t + __import__("datetime").timedelta(hours=h)
                     for h in range(0, predict_hours, 24)]
        future_vals = [last_v + slope_per_hour * h for h in range(0, predict_hours, 24)]
        ax.plot(future_ts, future_vals, color="#ff4d4f", linewidth=1.2,
                linestyle="--", alpha=0.7, label="预测趋势")

    if threshold is not None:
        ax.axhline(y=threshold, color="#faad14", linestyle=":", linewidth=1, label=f"告警阈值 ({threshold})")

    ax.set_title(title, fontsize=12, fontweight="bold")
    ax.set_ylabel(ylabel, fontsize=10)
    ax.legend(fontsize=9, loc="upper left")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    return _fig_to_base64(fig)


def render_pie_chart(labels: list[str], values: list[float], title: str) -> str:
    """Render a pie chart. Returns base64 PNG."""
    fig, ax = plt.subplots(figsize=(5, 4), dpi=120)

    truncated_labels = [l[:15] + "..." if len(l) > 15 else l for l in labels]
    colors = plt.cm.Set3(np.linspace(0, 1, len(labels)))

    wedges, texts, autotexts = ax.pie(
        values, labels=truncated_labels, autopct="%1.1f%%",
        colors=colors, textprops={"fontsize": 8}, pctdistance=0.8,
    )
    ax.set_title(title, fontsize=12, fontweight="bold")
    fig.tight_layout()

    return _fig_to_base64(fig)


def render_bar_chart(labels: list[str], values: list[float], title: str, ylabel: str, colors: list[str] | None = None) -> str:
    """Render a horizontal bar chart. Returns base64 PNG."""
    fig, ax = plt.subplots(figsize=(7, 3.5), dpi=120)

    y_pos = range(len(labels))
    bar_colors = colors or ["#1677ff"] * len(labels)

    ax.barh(y_pos, values, color=bar_colors, height=0.6)
    ax.set_yticks(y_pos)
    ax.set_yticklabels([l[:20] + "..." if len(l) > 20 else l for l in labels], fontsize=9)
    ax.set_xlabel(ylabel, fontsize=10)
    ax.set_title(title, fontsize=12, fontweight="bold")
    ax.invert_yaxis()
    ax.grid(True, axis="x", alpha=0.3)
    fig.tight_layout()

    return _fig_to_base64(fig)


def render_severity_bar(severity_counts: dict[str, int], title: str) -> str:
    """Render severity distribution as colored bars."""
    order = ["critical", "high", "medium", "low", "informational"]
    color_map = {"critical": "#ff4d4f", "high": "#ff7a45", "medium": "#faad14", "low": "#1677ff", "informational": "#8c8c8c"}

    labels = [s for s in order if severity_counts.get(s, 0) > 0]
    values = [severity_counts.get(s, 0) for s in labels]
    colors = [color_map[s] for s in labels]

    if not labels:
        return ""

    return render_bar_chart(labels, values, title, "次数", colors)


def _fig_to_base64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")
