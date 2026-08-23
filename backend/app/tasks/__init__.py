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
    beat_schedule={
        "schedule-collections-every-minute": {
            "task": "tasks.schedule_collections",
            "schedule": 60.0,
        },
        "evaluate-alerts-every-2-minutes": {
            "task": "tasks.evaluate_alerts",
            "schedule": 120.0,
        },
        "check-report-schedules-hourly": {
            "task": "tasks.check_report_schedules",
            "schedule": 3600.0,
        },
    },
)

import app.tasks.collect  # noqa: E402, F401
import app.tasks.alert  # noqa: E402, F401
import app.tasks.report  # noqa: E402, F401
