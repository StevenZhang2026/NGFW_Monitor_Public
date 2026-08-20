from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class AlertMessage:
    title: str
    device_name: str
    metric_name: str
    severity: str
    message: str
    value: str | None = None
    timestamp: str | None = None


class BaseNotifier(ABC):
    @abstractmethod
    async def send(self, channel_config: dict, alert: AlertMessage) -> bool:
        """Send alert notification. Returns True on success."""
        ...

    @abstractmethod
    async def test(self, channel_config: dict) -> bool:
        """Send a test message to verify channel configuration."""
        ...
