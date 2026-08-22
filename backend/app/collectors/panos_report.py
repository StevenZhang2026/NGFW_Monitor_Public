"""
PAN-OS Report API collector for ACC data (top-applications, top-threats, etc).

Uses: GET /api/?type=report&reporttype=predefined&reportname=<name>&period=<period>&key=<key>

Returns multiple MetricResult entries per call (one per application/threat in the report).
"""

from datetime import datetime, timezone

import httpx
from lxml import etree

from app.collectors.base import BaseCollector, MetricResult
from app.collectors.registry import register_collector


@register_collector
class PanosReportCollector(BaseCollector):
    name = "panos_report"

    async def collect(self, device, metric_def) -> list[MetricResult]:
        try:
            url = f"https://{device.hostname}/api/"
            report_name = metric_def.parser.get("report_name", "")
            period = metric_def.parser.get("period", "last-hour")

            params = {
                "type": "report",
                "reporttype": "predefined",
                "reportname": report_name,
                "period": period,
                "key": device.api_key_decrypted,
            }

            async with httpx.AsyncClient(verify=False, timeout=60) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()

            root = etree.fromstring(response.content)
            if root.tag == "response":
                status = root.get("status")
                if status != "success":
                    msg = root.findtext(".//msg") or status
                    return [MetricResult.failure(device.id, metric_def.name, f"Report API returned: {msg}")]

            entries = root.findall(".//entry")
            if not entries:
                return []

            now = datetime.now(timezone.utc)
            value_field = metric_def.parser.get("value_field", "bytes")
            name_field = metric_def.parser.get("name_field", "name")
            label_name = metric_def.parser.get("label_name", "instance")
            extra_fields = metric_def.parser.get("extra_fields", [])

            results = []
            for entry in entries:
                name_val = entry.findtext(name_field)
                value_str = entry.findtext(value_field)
                if not name_val or value_str is None:
                    continue

                try:
                    value = float(value_str)
                except (ValueError, TypeError):
                    continue

                labels = {label_name: name_val}
                for field in extra_fields:
                    field_val = entry.findtext(field)
                    if field_val is not None:
                        labels[field] = field_val

                results.append(MetricResult(
                    timestamp=now,
                    device_id=device.id,
                    metric_name=metric_def.name,
                    value=value,
                    labels=labels,
                ))

            return results

        except Exception as e:
            return [MetricResult.failure(device.id, metric_def.name, str(e))]

    async def test_connection(self, device) -> bool:
        try:
            url = f"https://{device.hostname}/api/"
            params = {
                "type": "report",
                "reporttype": "predefined",
                "reportname": "top-applications",
                "period": "last-hour",
                "key": device.api_key_decrypted,
            }
            async with httpx.AsyncClient(verify=False, timeout=15) as client:
                response = await client.get(url, params=params)
            return response.status_code == 200
        except Exception:
            return False
