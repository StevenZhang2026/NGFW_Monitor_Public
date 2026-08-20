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
            value = self._extract_value(row, data_type)
            labels = {k: v for k, v in row.items() if k not in ("timestamp", "count", "value")}

            results.append(MetricResult(
                timestamp=timestamp,
                device_id=device_id,
                metric_name=f"acc_{data_type}",
                value=value,
                labels=labels,
            ))

        return results

    def _parse_timestamp(self, row: dict) -> datetime:
        for field in ("timestamp", "time", "date", "Receive Time"):
            if field in row and row[field]:
                try:
                    return datetime.fromisoformat(row[field].replace("Z", "+00:00"))
                except ValueError:
                    continue
        return datetime.now(timezone.utc)

    def _extract_value(self, row: dict, data_type: str) -> float:
        for field in ("count", "value", "sessions", "bytes", "repeat-count"):
            if field in row and row[field]:
                try:
                    return float(row[field])
                except ValueError:
                    continue
        return 1.0

    async def test_connection(self, device) -> bool:
        return True
