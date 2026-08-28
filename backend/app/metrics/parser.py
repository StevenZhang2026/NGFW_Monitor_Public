import re
from datetime import datetime, timezone

from lxml import etree

from app.collectors.base import MetricResult

# How a single-value parser reconciles more than one match.
#
# PA-440 has one dataplane, so `show session info` and `show running
# resource-monitor` each yield exactly one figure per field. PA-5500 and PA-7000
# report per dataplane, so the same expression matches once per DP. Quietly
# keeping the first match would report DP0 alone — a plausible-looking number
# that under-states the device by a factor of its DP count, with no error to
# notice. So multiple matches are a hard failure unless the metric declares how
# to combine them.
#
# `sum` for additive totals (sessions, cps, kbps), `max` for a worst-DP
# saturation reading (packet buffer / descriptor), `first` only where the
# duplicates are known to be redundant.
_REDUCERS = {
    "sum": sum,
    "max": max,
    "min": min,
    "avg": lambda vs: sum(vs) / len(vs),
    "first": lambda vs: vs[0],
}


# Named expressions a metric definition can ask for in `parser.calc`. A fixed
# set rather than an eval'd expression: these come from admin-editable config,
# so an expression language here would be both an injection surface and a way
# for a typo to produce a plausible-looking wrong number.
_CALCS = {
    "value1 / value0 * 100": lambda vs: vs[1] / vs[0] * 100 if vs[0] > 0 else 0.0,
    "100 - value0": lambda vs: 100 - vs[0],
}


def _enforce_range(results, config):
    """Fail any value outside the range the metric declares in `parser.range`.

    A CPU reading of 112.3% is not a measurement, it is a parse that went wrong
    upstream — and once stored as a number it looks authoritative forever, feeds
    threshold alerts and skews capacity forecasts. Declaring a range turns that
    into a collection failure, which is visible.

    Optional: a metric with no declared range is unchanged.
    """
    bounds = config.get("range")
    if not bounds:
        return results

    low, high = float(bounds[0]), float(bounds[1])
    return [
        r if not r.success or low <= r.value <= high
        else MetricResult.failure(
            r.device_id, r.metric_name,
            f"value {r.value} outside declared range [{low}, {high}]",
        )
        for r in results
    ]


def _reduce_matches(values, config, device_id, metric_name, source):
    """Collapse several matches into one value. Returns (value, failure).

    Exactly one of the two is None.
    """
    if len(values) == 1:
        return values[0], None

    policy = config.get("on_multiple")
    reducer = _REDUCERS.get(policy) if policy else None
    if reducer is None:
        detail = (
            f"unknown on_multiple '{policy}'" if policy
            else "set parser.on_multiple to one of "
                 f"{sorted(_REDUCERS)} (sum for additive totals such as sessions "
                 "or throughput, max for saturation readings), or narrow the "
                 "expression to a single node"
        )
        return None, MetricResult.failure(
            device_id, metric_name,
            f"{source} matched {len(values)} values {values[:6]} — {detail}",
        )
    return reducer(values), None


def parse_value(xml_root: etree._Element, parser_config: dict, device_id: str, metric_name: str) -> list[MetricResult]:
    """Parse values from XML API response based on parser configuration."""
    parser_type = parser_config.get("type", "xpath")
    now = datetime.now(timezone.utc)

    if parser_type == "xpath":
        results = _parse_xpath(xml_root, parser_config, device_id, metric_name, now)
    elif parser_type == "xpath_multi":
        results = _parse_xpath_multi(xml_root, parser_config, device_id, metric_name, now)
    elif parser_type == "regex_cdata":
        results = _parse_regex_cdata(xml_root, parser_config, device_id, metric_name, now)
    elif parser_type == "regex_cdata_fields":
        results = _parse_regex_cdata_fields(xml_root, parser_config, device_id, metric_name, now)
    else:
        return [MetricResult.failure(device_id, metric_name, f"Unknown parser type: {parser_type}")]

    return _enforce_range(results, parser_config)


def _parse_xpath(root, config, device_id, metric_name, now) -> list[MetricResult]:
    expr = config["expr"]
    result_node = root.xpath(expr)
    if not result_node:
        return [MetricResult.failure(device_id, metric_name, f"XPath '{expr}' returned nothing")]

    if not isinstance(result_node, list):
        result_node = [result_node]

    values = []
    for node in result_node:
        raw = node.text if hasattr(node, "text") else str(node)
        cleaned = re.sub(r"[^\d.\-]", "", raw or "")
        try:
            values.append(float(cleaned))
        except ValueError:
            return [MetricResult.failure(device_id, metric_name, f"Cannot parse value: {cleaned}")]

    value, failure = _reduce_matches(
        values, config, device_id, metric_name, f"XPath '{expr}'"
    )
    if failure:
        return [failure]

    return [MetricResult(timestamp=now, device_id=device_id, metric_name=metric_name, value=value)]


def _parse_xpath_multi(root, config, device_id, metric_name, now) -> list[MetricResult]:
    """Parse multiple entries (e.g., per-interface stats)."""
    entries_expr = config["entries_expr"]
    value_expr = config["value_expr"]
    label_expr = config.get("label_expr", "@name")

    entries = root.xpath(entries_expr)
    results = []
    for entry in entries:
        label_nodes = entry.xpath(label_expr)
        label = label_nodes[0] if label_nodes else "unknown"
        if hasattr(label, "text"):
            label = label.text or "unknown"

        value_nodes = entry.xpath(value_expr)
        if not value_nodes:
            continue
        value_str = value_nodes[0].text if hasattr(value_nodes[0], "text") else str(value_nodes[0])
        value_str = re.sub(r"[^\d.\-]", "", value_str)
        try:
            value = float(value_str)
        except ValueError:
            continue

        results.append(MetricResult(
            timestamp=now,
            device_id=device_id,
            metric_name=metric_name,
            value=value,
            labels={"instance": str(label)},
        ))

    return results


def _parse_regex_cdata(root, config, device_id, metric_name, now) -> list[MetricResult]:
    """Parse regex from CDATA text content inside XML response (e.g., show system resources)."""
    text = etree.tostring(root, method="text", encoding="unicode")
    pattern = config["pattern"]
    match = re.search(pattern, text)
    if not match:
        return [MetricResult.failure(device_id, metric_name, f"Regex '{pattern}' no match in CDATA")]

    calc = config.get("calc")
    if calc is not None and calc not in _CALCS:
        return [MetricResult.failure(
            device_id, metric_name,
            f"unknown calc '{calc}' — expected one of {sorted(_CALCS)}",
        )]

    groups = match.groups()
    try:
        if calc is None:
            value = float(groups[0])
        else:
            value = _CALCS[calc]([float(g) for g in groups])
    except (ValueError, TypeError):
        return [MetricResult.failure(device_id, metric_name, f"Cannot parse values: {groups}")]
    except IndexError:
        return [MetricResult.failure(
            device_id, metric_name,
            f"calc '{calc}' needs more capture groups than pattern '{pattern}' has",
        )]

    return [MetricResult(timestamp=now, device_id=device_id, metric_name=metric_name, value=round(value, 2))]


def _parse_regex_cdata_fields(root, config, device_id, metric_name, now) -> list[MetricResult]:
    """Sum the `<number> <label>` fields on one line, minus the ones in `exclude`.

    For lines where a fixed capture-group expression cannot express the answer,
    because the set of fields is not fixed. `top`'s `%Cpu(s)` is the case this
    exists for.

    Measured on PA-440 (4 cores, PAN-OS 11.x): the fields on that line do not
    add up to 100, and the shortfall moves with load — sums of 33.3 / 39.9 /
    53.0 / 86.6 / 92.5 across five samples four seconds apart. So `100 - id` is
    not the utilisation: it read 86.7% and 100% on the two samples where the
    process list accounted for 18.6% and 81.1% of CPU. `us` alone does track
    the process list, but drops sy/ni/hi, which came to 11.6 points on the busy
    sample — the difference between alerting and not, at a threshold of 80.
    Summing everything that is not idle matched the process list on both
    samples (22.1 vs 18.6, 86.5 vs 81.1).

    Fields are captured by name rather than by position so that a top version
    which adds a field (gnice, st) has it counted rather than silently dropped
    — which is what made the fixed-group version unsafe to sum.
    """
    text = etree.tostring(root, method="text", encoding="unicode")
    pattern = config["pattern"]
    match = re.search(pattern, text)
    if not match:
        return [MetricResult.failure(device_id, metric_name, f"Regex '{pattern}' no match in CDATA")]

    # The capture group narrows the search to one line; without one, patterns
    # like `[\d.]+ \w+` would also match figures on the Mem / Swap lines.
    segment = match.group(1) if match.groups() else match.group(0)

    field_pattern = config["field_pattern"]
    fields = re.findall(field_pattern, segment)
    if not fields:
        return [MetricResult.failure(
            device_id, metric_name,
            f"field_pattern '{field_pattern}' matched no fields in '{segment.strip()}'",
        )]

    try:
        values = {name: float(raw) for raw, name in fields}
    except ValueError:
        return [MetricResult.failure(device_id, metric_name, f"Cannot parse fields: {fields}")]

    exclude = config.get("exclude", [])
    # A name that is not on the line means either a typo in the config or a
    # changed output format. Left unchecked, the field it was meant to remove
    # would simply be counted as load — a plausible-looking overestimate.
    missing = [name for name in exclude if name not in values]
    if missing:
        return [MetricResult.failure(
            device_id, metric_name,
            f"excluded field(s) {missing} not on the line, found {sorted(values)}",
        )]

    total = sum(v for name, v in values.items() if name not in exclude)
    return [MetricResult(timestamp=now, device_id=device_id, metric_name=metric_name, value=round(total, 2))]


def parse_value_text(text: str, parser_config: dict, device_id: str, metric_name: str) -> list[MetricResult]:
    """Parse values from CLI text output based on parser configuration."""
    parser_type = parser_config.get("type", "regex")
    now = datetime.now(timezone.utc)

    if parser_type == "regex":
        results = _parse_regex(text, parser_config, device_id, metric_name, now)
    elif parser_type == "regex_multi":
        results = _parse_regex_multi(text, parser_config, device_id, metric_name, now)
    else:
        return [MetricResult.failure(device_id, metric_name, f"Unknown text parser type: {parser_type}")]

    return _enforce_range(results, parser_config)


def _parse_regex(text, config, device_id, metric_name, now) -> list[MetricResult]:
    pattern = config["pattern"]
    # `show running resource-monitor` prints one block per dataplane, so the same
    # pattern matches once per DP on PA-5500/PA-7000. Same reasoning as the XPath
    # path: never silently keep only the first block.
    matches = list(re.finditer(pattern, text))
    if not matches:
        return [MetricResult.failure(device_id, metric_name, f"Regex '{pattern}' no match")]

    values = []
    for match in matches:
        value_str = match.group(1)
        try:
            values.append(float(value_str))
        except ValueError:
            return [MetricResult.failure(device_id, metric_name, f"Cannot parse value: {value_str}")]

    value, failure = _reduce_matches(
        values, config, device_id, metric_name, f"Regex '{pattern}'"
    )
    if failure:
        return [failure]

    return [MetricResult(timestamp=now, device_id=device_id, metric_name=metric_name, value=value)]


def _parse_regex_multi(text, config, device_id, metric_name, now) -> list[MetricResult]:
    pattern = config["pattern"]
    results = []
    for match in re.finditer(pattern, text):
        groups = match.groups()
        if len(groups) >= 2:
            label, value_str = groups[0], groups[1]
        else:
            label, value_str = "default", groups[0]
        try:
            value = float(value_str)
        except ValueError:
            continue
        results.append(MetricResult(
            timestamp=now,
            device_id=device_id,
            metric_name=metric_name,
            value=value,
            labels={"instance": label},
        ))
    return results
