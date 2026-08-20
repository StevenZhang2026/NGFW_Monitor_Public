from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class MetricResult:
    timestamp: datetime
    device_id: str
    metric_name: str
    value: float
    labels: dict = field(default_factory=dict)
    success: bool = True
    error: str | None = None

    @classmethod
    def failure(cls, device_id: str, metric_name: str, error: str) -> "MetricResult":
        return cls(
            timestamp=datetime.now(timezone.utc),
            device_id=device_id,
            metric_name=metric_name,
            value=0.0,
            success=False,
            error=error,
        )


class BaseCollector(ABC):
    name: str = "base"

    @abstractmethod
    async def collect(self, device, metric_def) -> list[MetricResult]:
        """Execute collection for a given device and metric definition.

        Returns a list because some metrics produce multiple values
        (e.g., per-interface stats).
        """
        ...

    @abstractmethod
    async def test_connection(self, device) -> bool:
        """Test connectivity to the device using this collector."""
        ...
