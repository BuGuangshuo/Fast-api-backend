"""Celery 应用配置。

本地开发使用 Redis 作为 broker，无 result backend。
"""

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    f"{settings.PROJECT_NAME}_worker",
    broker=settings.CELERY_BROKER_URL,
)

celery_app.conf.update(
    result_backend=None,
    task_ignore_result=True,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=False,
    worker_max_tasks_per_child=100,
    beat_schedule={
        "framework-healthcheck": {
            "task": "app.tasks.healthcheck.framework_healthcheck_task",
            "schedule": settings.CELERY_BEAT_HEALTHCHECK_INTERVAL_SECONDS,
        },
    },
)

celery_app.autodiscover_tasks(["app"])
