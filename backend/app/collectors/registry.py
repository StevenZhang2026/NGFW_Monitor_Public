from app.collectors.base import BaseCollector


class CollectorRegistry:
    def __init__(self):
        self._collectors: dict[str, BaseCollector] = {}

    def register(self, collector: BaseCollector):
        self._collectors[collector.name] = collector

    def get(self, name: str) -> BaseCollector | None:
        return self._collectors.get(name)

    def list_all(self) -> list[str]:
        return list(self._collectors.keys())


collector_registry = CollectorRegistry()


def register_collector(cls):
    """Decorator to auto-register a collector class."""
    instance = cls()
    collector_registry.register(instance)
    return cls
