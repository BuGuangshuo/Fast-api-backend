import asyncio
import logging

from sqlalchemy import Engine
from sqlmodel import Session, select
from tenacity import after_log, before_log, retry, stop_after_attempt, wait_fixed

from app.core.db import engine
from app.core.redis import redis_manager
from app.utils import get_logger

logger = get_logger(__name__)

max_tries = 60 * 5
wait_seconds = 1


@retry(
    stop=stop_after_attempt(max_tries),
    wait=wait_fixed(wait_seconds),
    before=before_log(logger, logging.INFO),
    after=after_log(logger, logging.WARN),
)
def init_db(db_engine: Engine) -> None:
    """等待数据库可连接。"""
    with Session(db_engine) as session:
        session.exec(select(1))


@retry(
    stop=stop_after_attempt(max_tries),
    wait=wait_fixed(wait_seconds),
    before=before_log(logger, logging.INFO),
    after=after_log(logger, logging.WARN),
)
async def init_redis() -> None:
    """等待 Redis 可连接。"""
    await redis_manager.init_redis()


async def init_all_dependencies() -> None:
    logger.info("初始化数据库连接")
    init_db(engine)
    logger.info("数据库初始化成功")

    logger.info("初始化 Redis 连接")
    await init_redis()
    logger.info("Redis 初始化成功")


async def shutdown_all_dependencies() -> None:
    logger.info("开始释放资源")
    await redis_manager.close_redis()


async def async_main() -> None:
    await init_all_dependencies()
    await shutdown_all_dependencies()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
