from datetime import datetime, timezone

import httpx
from lxml import etree

from app.collectors.base import BaseCollector, MetricResult
from app.collectors.registry import register_collector
from app.metrics.parser import parse_value


@register_collector
class PanosApiCollector(BaseCollector):
    name = "panos_api"

    async def collect(self, device, metric_def) -> list[MetricResult]:
        try:
            url = f"https://{device.hostname}/api/"
            params = {
                "type": "op",
                "cmd": metric_def.command,
                "key": device.api_key_decrypted,
            }
            async with httpx.AsyncClient(verify=False, timeout=30) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()

            root = etree.fromstring(response.content)
            status = root.get("status")
            if status != "success":
                return [MetricResult.failure(device.id, metric_def.name, f"API returned status: {status}")]

            results = parse_value(root, metric_def.parser, device.id, metric_def.name)
            return results

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
