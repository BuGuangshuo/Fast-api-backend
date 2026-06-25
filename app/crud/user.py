"""用户 CRUD 操作。"""

import uuid

from sqlmodel import Session, select

from app.core.security import get_password_hash
from app.models import User, utc_now
from app.schemas import UserCreate


def get_user_by_id(session: Session, user_id: uuid.UUID) -> User | None:
    """按主键读取用户。"""
    return session.get(User, user_id)


def get_user_by_username(session: Session, username: str) -> User | None:
    """按用户名读取用户，用于登录认证和唯一性校验。"""
    statement = select(User).where(User.username == username)
    return session.exec(statement).first()


def get_user_by_email(session: Session, email: str) -> User | None:
    """按邮箱读取用户，用于唯一性校验。"""
    statement = select(User).where(User.email == email)
    return session.exec(statement).first()


def create_user(session: Session, user_create: UserCreate) -> User:
    """创建用户并写入密码哈希。"""
    user = User(
        username=user_create.username,
        email=str(user_create.email) if user_create.email else None,
        full_name=user_create.full_name,
        is_active=user_create.is_active,
        is_superuser=user_create.is_superuser,
        hashed_password=get_password_hash(user_create.password),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def update_user_last_login(session: Session, user: User) -> User:
    """登录成功后回写最近登录时间。"""
    now = utc_now()
    user.last_login_at = now
    user.updated_at = now
    session.add(user)
    session.commit()
    session.refresh(user)
    return user
