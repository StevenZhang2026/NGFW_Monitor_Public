import asyncio
from datetime import datetime, timezone

from app.tasks import celery_app
from app.tasks.collect import _get_session
from app.alerts.engine import alert_rule_handlers


@celery_app.task(name="tasks.evaluate_alerts")
def evaluate_alerts():
    """Evaluate all enabled alert rules."""
    asyncio.run(_evaluate_alerts())


async def _evaluate_alerts():
    from sqlalchemy import select
    from app.models.alert import AlertRule, AlertEvent, AlertStatus
    from app.models.device import Device
    from app.alerts.health import HEALTH_RULE_METRIC
    from app.alerts.notify import in_notify_cooldown, notify_channels
    from app.alerts.notifiers.base import AlertMessage

    async with _get_session() as session:
        rules = (await session.execute(
            select(AlertRule).where(AlertRule.enabled == True)
        )).scalars().all()

        for rule in rules:
            # The collection-health rule carries configuration only; its signals
            # come from the scheduler's own state, not from metric_data, so
            # tasks.check_collection_health evaluates it instead of a handler.
            if rule.metric_name == HEALTH_RULE_METRIC:
                continue

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

                    # Asked before the event is added: an autoflushed pending
                    # row would count itself and suppress its own notification.
                    silenced = await in_notify_cooldown(session, rule, device_id)

                    session.add(AlertEvent(
                        rule_id=rule.id,
                        device_id=device_id,
                        metric_name=rule.metric_name,
                        severity=rule.severity,
                        status=AlertStatus.firing,
                        message=evaluation.message,
                        value=str(evaluation.value) if evaluation.value else None,
                        triggered_at=datetime.now(timezone.utc),
                    ))

                    if silenced:
                        continue

                    await notify_channels(session, rule, AlertMessage(
                        title=rule.name,
                        device_name=device_name,
                        metric_name=rule.metric_name,
                        severity=rule.severity.value,
                        message=evaluation.message,
                        value=str(evaluation.value) if evaluation.value else None,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    ))

        await session.commit()
