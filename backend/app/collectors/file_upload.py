import csv
import io
from datetime import datetime, timezone

from app.collectors.base import BaseCollector, MetricResult
from app.collectors.registry import register_collector


@register_collector
class FileUploadCollector(BaseCollector):
    name = "file_upload"

    async def collect(self, device, metric_def) -> list[MetricResult]:
        raise NotImplementedError("FileUploadCollector does not support scheduled collection")

    async def parse_csv(self, file_content: bytes, device_id: str, data_type: str) -> list[MetricResult]:
        results = []
        text = file_content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))

        for row in reader:
            timestamp = self._parse_timestamp(row)
            parsed = self._parse_row(row, data_type)
            if parsed is None:
                continue

            metric_name, value, labels = parsed
            results.append(MetricResult(
                timestamp=timestamp,
                device_id=device_id,
                metric_name=metric_name,
                value=value,
                labels=labels,
            ))

        return results

    def _parse_row(self, row: dict, data_type: str) -> tuple[str, float, dict] | None:
        if data_type in ("traffic", "application"):
            app_name = row.get("Application") or row.get("application") or row.get("app")
            if not app_name:
                return None
            bytes_val = self._to_float(row.get("Bytes") or row.get("bytes") or "0")
            sessions = row.get("Sessions") or row.get("sessions") or "0"
            labels = {"application": app_name, "sessions": sessions}
            if "Risk" in row:
                labels["risk"] = row["Risk"]
            if "Threats" in row:
                labels["threats"] = row["Threats"]
            return "acc_application", bytes_val, labels

        elif data_type == "threat":
            threat_name = (
                row.get("Threat/Content Name")
                or row.get("threat_name")
                or row.get("Name")
                or ""
            )
            if not threat_name:
                return None
            count_val = self._to_float(row.get("Count") or row.get("count") or "1")
            labels = {"threat_name": threat_name}
            if "Severity" in row:
                labels["severity"] = row["Severity"]
            if "Threat Category" in row or "threat-type" in row:
                labels["category"] = row.get("Threat Category") or row.get("threat-type", "")
            if "ID" in row:
                labels["threat_id"] = row["ID"]
            return "acc_threat", count_val, labels

        else:
            value = self._to_float(
                row.get("count") or row.get("value") or row.get("bytes") or "1"
            )
            labels = {k: v for k, v in row.items() if k not in ("timestamp", "count", "value")}
            return f"acc_{data_type}", value, labels

    def _parse_timestamp(self, row: dict) -> datetime:
        for field in ("timestamp", "time", "date", "Receive Time"):
            if field in row and row[field]:
                try:
                    return datetime.fromisoformat(row[field].replace("Z", "+00:00"))
                except ValueError:
                    continue
        return datetime.now(timezone.utc)

    def _to_float(self, val: str) -> float:
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0

    async def test_connection(self, device) -> bool:
        return True
