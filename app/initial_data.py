from sqlmodel import Session

from app.core.db import engine, init_db
from app.utils import get_logger

logger = get_logger(__name__)


def init() -> None:
    """初始化基础数据。骨架项目暂不写入业务数据。"""
    with Session(engine) as session:
        init_db(session)


def main() -> None:
    logger.info("Creating initial data")
    init()
    logger.info("Initial data created")


if __name__ == "__main__":
    main()
