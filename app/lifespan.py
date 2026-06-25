from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.redis import redis_manager
from app.utils import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:  # noqa: ARG001
    """应用生命周期管理：初始化并关闭 Redis 连接池。"""
    logger.info("正在初始化 Redis 连接...")
    await redis_manager.init_redis()
    logger.info("应用启动完成")

    yield

    logger.info("正在关闭应用...")
    await redis_manager.close_redis()
    logger.info("应用关闭完成")
