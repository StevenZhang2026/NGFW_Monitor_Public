from app.alerts.notifiers.base import BaseNotifier
from app.alerts.notifiers.feishu import FeishuNotifier
from app.alerts.notifiers.email import EmailNotifier
from app.alerts.notifiers.wechat import WechatNotifier

notifier_registry: dict[str, type[BaseNotifier]] = {
    "feishu": FeishuNotifier,
    "email": EmailNotifier,
    "wechat": WechatNotifier,
}

__all__ = ["BaseNotifier", "FeishuNotifier", "EmailNotifier", "WechatNotifier", "notifier_registry"]
