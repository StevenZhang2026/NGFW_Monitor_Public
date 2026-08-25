"""Periodic check that the collection pipeline is keeping up.

The signal definitions live in app.alerts.health; this is the scheduling and
event bookkeeping around them.
"""

import asyncio
from datetime import datetime, timezone

from app.tasks import celery_app
from app.tasks.collect import _get_session


@celery_app.task(name="tasks.check_collection_health")
def check_collection_health():
    """Turn collection lag into alert events on the builtin health rule."""
    asyncio.run(_check_collection_health())


async def _check_collection_health():
    from sqlalchemy import select
    from app.alerts.health import HEALTH_RULE_METRIC, evaluate_collection_health
    from app.alerts.notify import in_notify_cooldown, notify_channels
    from app.alerts.notifiers.base import AlertMessage
    from app.models.alert import AlertEvent, AlertRule, AlertStatus
    from app.models.device import Device
    from app.models.metric import MetricDefinition

    async with _get_session() as session:
        rule = (await session.execute(
            select(AlertRule).where(AlertRule.metric_name == HEALTH_RULE_METRIC)
        )).scalars().first()
        if rule is None or not rule.enabled:
            return

        devices = (await session.execute(
            select(Device).where(Device.collect_enabled == True)
        )).scalars().all()
        if rule.device_ids:
            devices = [d for d in devices if d.id in rule.device_ids]

        metrics = (await session.execute(
            select(MetricDefinition).where(MetricDefinition.enabled == True)
        )).scalars().all()

        findings = await evaluate_collection_health(session, rule, devices, metrics)

        # One open event per problem. Without this, a metric that stopped a week
        # ago would add an event on every check and bury the event list; the
        # cooldown only gates notifications, not rows.
        open_events = (await session.execute(
            select(AlertEvent).where(
                AlertEvent.rule_id == rule.id,
                AlertEvent.status == AlertStatus.firing,
            )
        )).scalars().all()
        open_by_key = {(e.device_id, e.metric_name): e for e in open_events}

        now = datetime.now(timezone.utc)
        for finding in findings:
            if finding.key in open_by_key:
                continue

            # Asked before the event is added: an autoflushed pending row would
            # count itself and suppress its own notification.
            silenced = await in_notify_cooldown(
                session, rule, finding.device_id, finding.metric_name
            )
            session.add(AlertEvent(
                rule_id=rule.id,
                device_id=finding.device_id,
                metric_name=finding.metric_name,
                severity=finding.severity,
                status=AlertStatus.firing,
                message=finding.message,
                value=finding.value,
                triggered_at=now,
            ))
            if silenced:
                continue

            await notify_channels(session, rule, AlertMessage(
                title=rule.name,
                device_name=finding.device_name,
                metric_name=finding.metric_name,
                severity=finding.severity.value,
                message=finding.message,
                value=finding.value,
                timestamp=now.isoformat(),
            ))

        # Anything that stopped being reported has recovered. Closing it matters
        # beyond tidiness: an event left firing forever would block the same
        # problem from ever being reported again.
        current = {f.key for f in findings}
        for key, event in open_by_key.items():
            if key not in current:
                event.status = AlertStatus.resolved
                event.resolved_at = now

        await session.commit()
