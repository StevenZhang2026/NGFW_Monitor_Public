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


@dataclass
class SendResult:
    success: bool
    error: str | None = None


class BaseNotifier(ABC):
    @abstractmethod
    async def send(self, channel_config: dict, alert: AlertMessage) -> SendResult:
        """Send alert notification."""
        ...

    @abstractmethod
    async def test(self, channel_config: dict) -> SendResult:
        """Send a test message to verify channel configuration."""
        ...
