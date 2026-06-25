"""框架级 Celery 健康检查任务。"""

from app.core.celery_app import celery_app
from app.utils import get_logger

logger = get_logger(__name__)


@celery_app.task(name="app.tasks.healthcheck.framework_healthcheck_task")
def framework_healthcheck_task() -> None:
    """用于验证 Celery worker 与 beat 链路已正确注册。"""
    logger.info("framework healthcheck task executed")
