"""Fan an alert out to the channels its rule points at.

Shared by the metric alert evaluator and the collection-health check so a
second alert source does not grow a second copy of the channel handling and
cooldown rules.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.alerts.notifiers import notifier_registry
from app.alerts.notifiers.base import AlertMessage, SendResult

logger = logging.getLogger(__name__)


async def in_notify_cooldown(session, rule, device_id: str, metric_name: str | None = None) -> bool:
    """Whether this rule already notified about this subject recently.

    Must be called *before* the new AlertEvent is added to the session.
    Autoflush would flush the pending row and count it, making the cooldown
    permanently true and silencing every notification the rule would ever
    send — the event history would fill up while nobody was told.
    """
    from app.models.alert import AlertEvent

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=rule.notify_interval or 30)
    query = select(func.count(AlertEvent.id)).where(
        AlertEvent.rule_id == rule.id,
        AlertEvent.device_id == device_id,
        AlertEvent.triggered_at > cutoff,
    )
    if metric_name is not None:
        query = query.where(AlertEvent.metric_name == metric_name)
    return (await session.execute(query)).scalar_one() > 0


async def notify_channels(session, rule, alert: AlertMessage) -> list[SendResult]:
    """Send one alert to every enabled channel on the rule.

    A channel that fails is logged and skipped: one broken webhook must not stop
    the remaining channels from being told.
    """
    from app.models.notification import NotificationChannel

    results: list[SendResult] = []
    for channel_id in rule.notification_channel_ids or []:
        channel = (await session.execute(
            select(NotificationChannel).where(NotificationChannel.id == channel_id)
        )).scalar_one_or_none()
        if not channel or not channel.enabled:
            continue

        notifier_cls = notifier_registry.get(channel.type.value)
        if not notifier_cls:
            logger.warning("no notifier registered for channel type %s", channel.type.value)
            continue

        result = await notifier_cls().send(channel.config, alert)
        if not result.success:
            logger.warning(
                "channel %s did not deliver alert '%s': %s", channel.name, alert.title, result.error
            )
        results.append(result)
    return results
