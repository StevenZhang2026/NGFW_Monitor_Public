from celery import Celery

from app.config import settings

celery_app = Celery("ngfw_monitor", broker=settings.redis_url, backend=settings.redis_url)

import app.collectors.panos_api  # noqa: E402, F401
import app.collectors.panos_ssh  # noqa: E402, F401
import app.collectors.panorama  # noqa: E402, F401
import app.collectors.panos_report  # noqa: E402, F401
import app.collectors.file_upload  # noqa: E402, F401

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    worker_concurrency=settings.collector_concurrency,
    # Collections are minutes-long I/O, not short CPU work, so prefetching them
    # only hides them: reserved tasks sit in one worker's memory where the queue
    # depth cannot see them and where they age towards their own expiry while
    # another worker is idle. One task per slot keeps the backlog measurable.
    worker_prefetch_multiplier=1,
    beat_schedule={
        "schedule-collections-every-minute": {
            "task": "tasks.schedule_collections",
            "schedule": float(settings.collect_beat_interval),
        },
        "evaluate-alerts-every-2-minutes": {
            "task": "tasks.evaluate_alerts",
            "schedule": 120.0,
        },
        "check-collection-health": {
            "task": "tasks.check_collection_health",
            "schedule": float(settings.collection_health_interval),
        },
        "check-report-schedules-hourly": {
            "task": "tasks.check_report_schedules",
            "schedule": 3600.0,
        },
    },
)

import app.tasks.collect  # noqa: E402, F401
import app.tasks.alert  # noqa: E402, F401
import app.tasks.health  # noqa: E402, F401
import app.tasks.report  # noqa: E402, F401
