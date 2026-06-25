"""Celery task package."""

from app.tasks.healthcheck import framework_healthcheck_task

__all__ = ["framework_healthcheck_task"]
