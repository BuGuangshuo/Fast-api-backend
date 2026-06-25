"""日志配置模块。"""

import logging
import sys
from functools import cache

from app.core.config import settings

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _setup_logging() -> None:
    """配置根日志器。"""
    level = logging.DEBUG if settings.ENVIRONMENT == "local" else logging.INFO
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt=DATE_FORMAT,
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


_setup_logging()


@cache
def get_logger(name: str) -> logging.Logger:
    """获取 logger 实例。"""
    return logging.getLogger(name)
