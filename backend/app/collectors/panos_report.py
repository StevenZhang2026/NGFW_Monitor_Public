"""
PAN-OS dynamic report collector for ACC data (application usage, threat activity).

Aggregation happens on the device, not here:
  GET /api/?type=report&reporttype=dynamic&reportname=<name>
          &topn=<n>&start-time=<t>&end-time=<t>&key=<key>

The firewall aggregates over its full log database and returns a ranked
summary, so collection cost is independent of log volume. A PA-5450 doing
300k traffic logs an hour costs exactly the same as a PA-440 doing 200.

Windows are *aligned closed buckets* (15 min minimum, the device's own ACC
granularity). That makes each data point idempotent — asking the device for
[10:00, 10:15) always yields the same numbers — so re-collection is safe and
gaps can be backfilled. Verified on PA-440 / PAN-OS 11.x: 15-minute buckets
sum exactly to the containing hour.

Report windows are expressed in the *device's* local time, which is derived
from `show clock` rather than hardcoded, so the same code works wherever the
firewall happens to live.
"""

import asyncio
import re
from collections import defaultdict
from datetime import datetime, timezone, timedelta

import httpx
from lxml import etree

from app.collectors.base import BaseCollector, MetricResult
from app.collectors.registry import register_collector

# The device's smallest ACC aggregation granularity. Nothing below this is
# meaningful, so bucket sizes are floored to a multiple of it.
MIN_BUCKET_SECONDS = 900

# How long to let a just-closed bucket settle before asking for it, so we
# never read a window the device is still writing logs into.
DEFAULT_SETTLE_SECONDS = 120

POLL_INTERVAL = 2
POLL_TIMEOUT = 120
DEFAULT_TOPN = 100

_CLOCK_RE = re.compile(
    r"^\w{3}\s+(?P<mon>\w{3})\s+(?P<day>\d{1,2})\s+"
    r"(?P<time>\d{2}:\d{2}:\d{2})\s+\S+\s+(?P<year>\d{4})"
)


def bucket_marker_name(metric_name: str) -> str:
    """Name of the row recording that a bucket was collected.

    A bucket with no traffic yields no data rows, which is indistinguishable
    from "never collected" — the scheduler would then re-request the same empty
    window on every beat tick until it scrolls out. The marker makes the
    distinction explicit. The `_bucket::` prefix keeps it out of every query
    that scans `<metric>::%`, so it never surfaces as an instance or a ranking.
    """
    return f"_bucket::{metric_name}"


def bucket_seconds(metric_def) -> int:
    """Bucket size for a metric: the admin-set interval, floored to a
    multiple of the device's 15-minute granularity."""
    interval = getattr(metric_def, "interval", MIN_BUCKET_SECONDS) or MIN_BUCKET_SECONDS
    return max(MIN_BUCKET_SECONDS, (interval // MIN_BUCKET_SECONDS) * MIN_BUCKET_SECONDS)


def target_bucket(metric_def, now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return the most recent fully-closed bucket as [start, end) in UTC.

    Bucket identity — not elapsed time — is what decides whether a data point
    is missing, because the stored timestamp always lags `now`.
    """
    now = now or datetime.now(timezone.utc)
    size = bucket_seconds(metric_def)
    settle = int((metric_def.parser or {}).get("settle_seconds", DEFAULT_SETTLE_SECONDS))

    ref = now - timedelta(seconds=settle)
    epoch = int(ref.timestamp())
    end_epoch = (epoch // size) * size
    end = datetime.fromtimestamp(end_epoch, tz=timezone.utc)
    return end - timedelta(seconds=size), end


@register_collector
class PanosReportCollector(BaseCollector):
    name = "panos_report"

    async def collect(self, device, metric_def) -> list[MetricResult]:
        cfg = metric_def.parser or {}
        reports = cfg.get("reports") or []
        if not reports:
            return [MetricResult.failure(
                device.id, metric_def.name, "parser.reports is empty")]

        start_utc, end_utc = target_bucket(metric_def)

        try:
            url = f"https://{device.hostname}/api/"
            async with httpx.AsyncClient(verify=False, timeout=90) as client:
                offset = await self._device_utc_offset(client, url, device)

                # The device interprets report windows in its own local time.
                # end-time is inclusive, so stop one second short of the next
                # bucket to keep adjacent buckets from overlapping.
                start_local = start_utc + offset
                end_local = end_utc + offset - timedelta(seconds=1)

                merged: dict[str, dict] = {}
                for report_name in reports:
                    entries = await self._run_report(
                        client, url, device, report_name,
                        start_local, end_local, int(cfg.get("topn", DEFAULT_TOPN)),
                    )
                    self._merge(merged, entries, cfg)

        except Exception as e:
            return [MetricResult.failure(device.id, metric_def.name, str(e))]

        label_name = cfg.get("label_name", "instance")
        results = [
            MetricResult(
                timestamp=start_utc,
                device_id=device.id,
                metric_name=f"{metric_def.name}::{key}",
                value=item["value"],
                labels={label_name: item["name"], **item["labels"]},
            )
            for key, item in merged.items()
        ]
        results.append(MetricResult(
            timestamp=start_utc,
            device_id=device.id,
            metric_name=bucket_marker_name(metric_def.name),
            value=float(len(merged)),
            labels={"bucket_seconds": bucket_seconds(metric_def)},
        ))
        return results

    async def _device_utc_offset(self, client, url, device) -> timedelta:
        """Derive the device's UTC offset from `show clock`.

        The timezone abbreviation is ambiguous (CST is both China and US
        Central), so compare the device's wall clock to ours instead.
        """
        resp = await client.get(url, params={
            "type": "op",
            "cmd": "<show><clock/></show>",
            "key": device.api_key_decrypted,
        })
        resp.raise_for_status()
        raw = (etree.fromstring(resp.content).findtext(".//result") or "").strip()
        m = _CLOCK_RE.match(raw)
        if not m:
            raise ValueError(f"cannot parse device clock: {raw!r}")

        local = datetime.strptime(
            f"{m['mon']} {m['day']} {m['year']} {m['time']}", "%b %d %Y %H:%M:%S"
        )
        delta = local - datetime.now(timezone.utc).replace(tzinfo=None)
        # Real offsets land on 15-minute boundaries; snap away request latency.
        quarters = round(delta.total_seconds() / 900)
        return timedelta(seconds=quarters * 900)

    async def _run_report(self, client, url, device, report_name,
                          start_local, end_local, topn) -> list:
        params = {
            "type": "report",
            "reporttype": "dynamic",
            "reportname": report_name,
            "topn": str(topn),
            "start-time": start_local.strftime("%Y/%m/%d %H:%M:%S"),
            "end-time": end_local.strftime("%Y/%m/%d %H:%M:%S"),
            "key": device.api_key_decrypted,
        }
        resp = await client.get(url, params=params)
        if resp.status_code != 200:
            msg = etree.fromstring(resp.content).findtext(".//msg") or resp.text
            raise RuntimeError(f"{report_name}: HTTP {resp.status_code}: {msg[:200]}")

        root = etree.fromstring(resp.content)
        if root.get("status") not in (None, "success"):
            raise RuntimeError(f"{report_name}: {root.findtext('.//msg') or root.get('status')}")

        job_id = (root.findtext(".//job/id") or root.findtext(".//job") or "").strip()
        if job_id.isdigit() and root.findtext(".//job/status") != "FIN":
            root = await self._poll(client, url, device, job_id, report_name)

        return root.findall(".//entry")

    async def _poll(self, client, url, device, job_id, report_name):
        elapsed = 0
        while elapsed < POLL_TIMEOUT:
            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
            resp = await client.get(url, params={
                "type": "report", "action": "get", "job-id": job_id,
                "key": device.api_key_decrypted,
            })
            root = etree.fromstring(resp.content)
            if root.findtext(".//job/status") == "FIN":
                return root
        raise TimeoutError(f"{report_name}: report job {job_id} did not finish")

    @staticmethod
    def _merge(merged: dict, entries: list, cfg: dict) -> None:
        """Fold report rows into the accumulator, keyed for uniqueness.

        The key must be unique within a bucket: PA-440 returns distinct
        vulnerabilities that share a display name but differ by `tid`, and
        the storage primary key is (timestamp, device_id, metric_name).
        """
        name_field = cfg.get("name_field", "name")
        key_field = cfg.get("key_field", name_field)
        value_field = cfg.get("value_field", "nbytes")
        label_fields: dict = cfg.get("label_fields") or {}

        for entry in entries:
            key = (entry.findtext(key_field) or "").strip()
            name = (entry.findtext(name_field) or "").strip() or key
            if not key:
                continue
            try:
                value = float(entry.findtext(value_field) or 0)
            except (TypeError, ValueError):
                continue

            slot = merged.setdefault(key, {"name": name, "value": 0.0, "labels": {}})
            slot["value"] += value
            for label, field in label_fields.items():
                val = entry.findtext(field)
                if val is not None and label not in slot["labels"]:
                    slot["labels"][label] = val.strip()

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
