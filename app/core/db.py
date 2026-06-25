from sqlmodel import Session, create_engine

from app.core.config import settings
from app.crud import create_user, get_user_by_username
from app.schemas import UserCreate

engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI))


def init_db(session: Session) -> None:
    """初始化数据库基础数据。

    表结构由 Alembic 迁移管理；这里仅在显式配置环境变量时创建首个超级管理员。
    """
    if not settings.FIRST_SUPERUSER_USERNAME or not settings.FIRST_SUPERUSER_PASSWORD:
        return

    user = get_user_by_username(session, settings.FIRST_SUPERUSER_USERNAME)
    if user is not None:
        return

    create_user(
        session,
        UserCreate(
            username=settings.FIRST_SUPERUSER_USERNAME,
            password=settings.FIRST_SUPERUSER_PASSWORD,
            email=settings.FIRST_SUPERUSER_EMAIL,
            is_superuser=True,
        ),
    )
