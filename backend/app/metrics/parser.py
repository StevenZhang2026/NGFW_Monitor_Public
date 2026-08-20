import re
from datetime import datetime, timezone

from lxml import etree

from app.collectors.base import MetricResult


def parse_value(xml_root: etree._Element, parser_config: dict, device_id: str, metric_name: str) -> list[MetricResult]:
    """Parse values from XML API response based on parser configuration."""
    parser_type = parser_config.get("type", "xpath")
    now = datetime.now(timezone.utc)

    if parser_type == "xpath":
        return _parse_xpath(xml_root, parser_config, device_id, metric_name, now)
    elif parser_type == "xpath_multi":
        return _parse_xpath_multi(xml_root, parser_config, device_id, metric_name, now)
    elif parser_type == "regex_cdata":
        return _parse_regex_cdata(xml_root, parser_config, device_id, metric_name, now)
    else:
        return [MetricResult.failure(device_id, metric_name, f"Unknown parser type: {parser_type}")]


def _parse_xpath(root, config, device_id, metric_name, now) -> list[MetricResult]:
    expr = config["expr"]
    result_node = root.xpath(expr)
    if not result_node:
        return [MetricResult.failure(device_id, metric_name, f"XPath '{expr}' returned nothing")]

    if isinstance(result_node, list):
        value_str = result_node[0].text if hasattr(result_node[0], "text") else str(result_node[0])
    else:
        value_str = str(result_node)

    value_str = re.sub(r"[^\d.\-]", "", value_str)
    try:
        value = float(value_str)
    except ValueError:
        return [MetricResult.failure(device_id, metric_name, f"Cannot parse value: {value_str}")]

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

    groups = match.groups()
    calc = config.get("calc")

    if calc and len(groups) >= 2:
        values = [float(g) for g in groups]
        if calc == "value1 / value0 * 100":
            value = values[1] / values[0] * 100 if values[0] > 0 else 0.0
        else:
            value = values[0]
    else:
        value = float(groups[0])

    return [MetricResult(timestamp=now, device_id=device_id, metric_name=metric_name, value=round(value, 2))]


def parse_value_text(text: str, parser_config: dict, device_id: str, metric_name: str) -> list[MetricResult]:
    """Parse values from CLI text output based on parser configuration."""
    parser_type = parser_config.get("type", "regex")
    now = datetime.now(timezone.utc)

    if parser_type == "regex":
        return _parse_regex(text, parser_config, device_id, metric_name, now)
    elif parser_type == "regex_multi":
        return _parse_regex_multi(text, parser_config, device_id, metric_name, now)
    else:
        return [MetricResult.failure(device_id, metric_name, f"Unknown text parser type: {parser_type}")]


def _parse_regex(text, config, device_id, metric_name, now) -> list[MetricResult]:
    pattern = config["pattern"]
    match = re.search(pattern, text)
    if not match:
        return [MetricResult.failure(device_id, metric_name, f"Regex '{pattern}' no match")]

    value_str = match.group(1)
    try:
        value = float(value_str)
    except ValueError:
        return [MetricResult.failure(device_id, metric_name, f"Cannot parse value: {value_str}")]

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
