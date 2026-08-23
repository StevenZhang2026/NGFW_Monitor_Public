import asyncio
from datetime import datetime, timedelta, timezone

from app.tasks import celery_app
from app.tasks.collect import _get_session
from app.alerts.engine import alert_rule_handlers


@celery_app.task(name="tasks.evaluate_alerts")
def evaluate_alerts():
    """Evaluate all enabled alert rules."""
    asyncio.run(_evaluate_alerts())


async def _evaluate_alerts():
    from sqlalchemy import select, func
    from app.models.alert import AlertRule, AlertEvent, AlertStatus, Severity
    from app.models.notification import NotificationChannel
    from app.models.device import Device
    from app.alerts.notifiers import notifier_registry
    from app.alerts.notifiers.base import AlertMessage

    async with _get_session() as session:
        rules = (await session.execute(
            select(AlertRule).where(AlertRule.enabled == True)
        )).scalars().all()

        for rule in rules:
            handler = alert_rule_handlers.get(rule.type)
            if not handler:
                continue

            for device_id in rule.device_ids:
                evaluation = await handler.evaluate(rule.metric_name, device_id, rule.condition)

                if evaluation.triggered:
                    device = (await session.execute(
                        select(Device).where(Device.id == device_id)
                    )).scalar_one_or_none()
                    device_name = device.name if device else device_id

                    event = AlertEvent(
                        rule_id=rule.id,
                        device_id=device_id,
                        metric_name=rule.metric_name,
                        severity=rule.severity,
                        status=AlertStatus.firing,
                        message=evaluation.message,
                        value=str(evaluation.value) if evaluation.value else None,
                        triggered_at=datetime.now(timezone.utc),
                    )
                    session.add(event)

                    cooldown_minutes = rule.notify_interval or 30
                    cutoff = datetime.now(timezone.utc) - timedelta(minutes=cooldown_minutes)
                    recent_count = (await session.execute(
                        select(func.count(AlertEvent.id)).where(
                            AlertEvent.rule_id == rule.id,
                            AlertEvent.device_id == device_id,
                            AlertEvent.triggered_at > cutoff,
                        )
                    )).scalar_one()

                    if recent_count > 0:
                        continue

                    for channel_id in rule.notification_channel_ids:
                        channel = (await session.execute(
                            select(NotificationChannel).where(NotificationChannel.id == channel_id)
                        )).scalar_one_or_none()
                        if not channel or not channel.enabled:
                            continue

                        notifier_cls = notifier_registry.get(channel.type.value)
                        if not notifier_cls:
                            continue

                        notifier = notifier_cls()
                        alert_msg = AlertMessage(
                            title=rule.name,
                            device_name=device_name,
                            metric_name=rule.metric_name,
                            severity=rule.severity.value,
                            message=evaluation.message,
                            value=str(evaluation.value) if evaluation.value else None,
                            timestamp=datetime.now(timezone.utc).isoformat(),
                        )
                        await notifier.send(channel.config, alert_msg)

        await session.commit()
