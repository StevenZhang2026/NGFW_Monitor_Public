from datetime import datetime, timezone

import httpx
from lxml import etree

from app.collectors.base import BaseCollector, MetricResult
from app.collectors.registry import register_collector


@register_collector
class PanoramaCollector(BaseCollector):
    name = "panorama"

    async def collect(self, device, metric_def) -> list[MetricResult]:
        try:
            url = f"https://{device.hostname}/api/"
            params = {
                "type": "report",
                "reporttype": "predefined",
                "reportname": metric_def.parser.get("report_name", ""),
                "period": metric_def.parser.get("period", "last-hour"),
                "key": device.api_key_decrypted,
            }
            if metric_def.parser.get("target_device"):
                params["cmd"] = (
                    f"<show><report><target>{metric_def.parser['target_device']}</target></report></show>"
                )

            async with httpx.AsyncClient(verify=False, timeout=60) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()

            root = etree.fromstring(response.content)
            status = root.get("status")
            if status != "success":
                return [MetricResult.failure(device.id, metric_def.name, f"Panorama returned: {status}")]

            results = []
            for entry in root.findall(".//entry"):
                value_str = entry.findtext(metric_def.parser.get("value_field", "count"))
                if value_str is not None:
                    results.append(MetricResult(
                        timestamp=datetime.now(timezone.utc),
                        device_id=device.id,
                        metric_name=metric_def.name,
                        value=float(value_str),
                        labels={
                            child.tag: child.text
                            for child in entry
                            if child.tag != metric_def.parser.get("value_field", "count")
                        },
                    ))
            return results or [MetricResult.failure(device.id, metric_def.name, "No data returned")]

        except Exception as e:
            return [MetricResult.failure(device.id, metric_def.name, str(e))]

    async def test_connection(self, device) -> bool:
        try:
            url = f"https://{device.hostname}/api/"
            params = {
                "type": "op",
                "cmd": "<show><system><info></info></system></show>",
                "key": device.api_key_decrypted,
            }
            async with httpx.AsyncClient(verify=False, timeout=10) as client:
                response = await client.get(url, params=params)
            return response.status_code == 200
        except Exception:
            return False
