"""
PAN-OS Log Query collector for ACC data (application usage, threat activity).

Uses the async log query API:
  1. Submit: GET /api/?type=log&log-type=<traffic|threat>&nlogs=<n>&query=<filter>&key=<key>
  2. Poll:   GET /api/?type=log&action=get&job-id=<id>&key=<key>

Aggregates raw log entries into per-application / per-threat summaries,
then stores one MetricResult per item (e.g., acc_application::dns-base).
"""

import asyncio
from collections import defaultdict
from datetime import datetime, timezone, timedelta

import httpx
from lxml import etree

from app.collectors.base import BaseCollector, MetricResult
from app.collectors.registry import register_collector

MAX_LOGS = 5000
POLL_INTERVAL = 2
POLL_TIMEOUT = 60


@register_collector
class PanosReportCollector(BaseCollector):
    name = "panos_report"

    async def collect(self, device, metric_def) -> list[MetricResult]:
        try:
            log_type = metric_def.parser.get("log_type", "traffic")
            lookback_seconds = metric_def.parser.get("lookback_seconds", 3600)

            start_time = datetime.now(timezone(timedelta(hours=8))) - timedelta(seconds=lookback_seconds)
            time_filter = start_time.strftime("%Y/%m/%d %H:%M:%S")
            query = f'(receive_time geq "{time_filter}")'

            entries = await self._query_logs(device, log_type, query)
            if entries is None:
                return [MetricResult.failure(device.id, metric_def.name, "Log query failed")]
            if not entries:
                return []

            now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

            if log_type == "traffic":
                return self._aggregate_traffic(entries, device.id, metric_def.name, now)
            else:
                return self._aggregate_threats(entries, device.id, metric_def.name, now)

        except Exception as e:
            return [MetricResult.failure(device.id, metric_def.name, str(e))]

    async def _query_logs(self, device, log_type: str, query: str) -> list | None:
        url = f"https://{device.hostname}/api/"
        key = device.api_key_decrypted

        async with httpx.AsyncClient(verify=False, timeout=30) as client:
            params = {
                "type": "log",
                "log-type": log_type,
                "nlogs": str(MAX_LOGS),
                "query": query,
                "key": key,
            }
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                return None

            root = etree.fromstring(resp.content)
            if root.get("status") != "success":
                return None

            job_el = root.find(".//job")
            if job_el is None or not job_el.text:
                return None

            job_id = job_el.text
            elapsed = 0
            while elapsed < POLL_TIMEOUT:
                await asyncio.sleep(POLL_INTERVAL)
                elapsed += POLL_INTERVAL

                poll_params = {"type": "log", "action": "get", "job-id": job_id, "key": key}
                resp = await client.get(url, params=poll_params)
                root = etree.fromstring(resp.content)
                status_el = root.find(".//job/status")
                if status_el is not None and status_el.text == "FIN":
                    return root.findall(".//entry")

        return None

    def _aggregate_traffic(self, entries, device_id: str, base_name: str, now: datetime) -> list[MetricResult]:
        app_data: dict[str, dict] = defaultdict(lambda: {"bytes": 0, "sessions": 0, "risk": "1"})

        for entry in entries:
            app = entry.findtext("app")
            if not app or app in ("insufficient-data", "incomplete", "non-syn-tcp"):
                continue
            bytes_val = int(entry.findtext("bytes") or "0")
            risk = entry.findtext("risk_of_app") or "1"

            app_data[app]["bytes"] += bytes_val
            app_data[app]["sessions"] += 1
            if int(risk) > int(app_data[app]["risk"]):
                app_data[app]["risk"] = risk

        results = []
        for app_name, data in app_data.items():
            results.append(MetricResult(
                timestamp=now,
                device_id=device_id,
                metric_name=f"{base_name}::{app_name}",
                value=float(data["bytes"]),
                labels={
                    "application": app_name,
                    "sessions": str(data["sessions"]),
                    "risk": data["risk"],
                },
            ))
        return results

    def _aggregate_threats(self, entries, device_id: str, base_name: str, now: datetime) -> list[MetricResult]:
        threat_data: dict[str, dict] = defaultdict(lambda: {"count": 0, "severity": "", "category": ""})

        for entry in entries:
            threat_name = entry.findtext("threatid") or entry.findtext("threat_name") or ""
            if not threat_name:
                continue
            # Remove trailing (TID) like "HTTP XSS Vulnerability(30845)"
            if "(" in threat_name:
                threat_name = threat_name[:threat_name.rfind("(")].strip()

            severity = entry.findtext("severity") or "informational"
            category = entry.findtext("subtype") or entry.findtext("category") or ""

            threat_data[threat_name]["count"] += 1
            sev_order = {"critical": 4, "high": 3, "medium": 2, "low": 1, "informational": 0}
            if sev_order.get(severity, 0) > sev_order.get(threat_data[threat_name]["severity"], -1):
                threat_data[threat_name]["severity"] = severity
            if not threat_data[threat_name]["category"]:
                threat_data[threat_name]["category"] = category

        results = []
        for threat_name, data in threat_data.items():
            results.append(MetricResult(
                timestamp=now,
                device_id=device_id,
                metric_name=f"{base_name}::{threat_name}",
                value=float(data["count"]),
                labels={
                    "threat_name": threat_name,
                    "severity": data["severity"],
                    "category": data["category"],
                },
            ))
        return results

    async def test_connection(self, device) -> bool:
        try:
            url = f"https://{device.hostname}/api/"
            params = {
                "type": "op",
                "cmd": "<show><system><info></info></system></show>",
                "key": device.api_key_decrypted,
            }
            async with httpx.AsyncClient(verify=False, timeout=15) as client:
                response = await client.get(url, params=params)
            return response.status_code == 200
        except Exception:
            return False
