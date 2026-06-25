"""SQLModel ORM models.

所有 ORM 模型集中放在本文件，后续业务模块继续按分区追加。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    """生成带 UTC 时区的时间戳。"""
    return datetime.now(timezone.utc)


# ==================== User / Auth ====================


class UserBase(SQLModel):
    """用户基础字段，用于登录认证和权限判断。"""

    username: str = Field(index=True, unique=True, max_length=64)
    email: str | None = Field(default=None, index=True, unique=True, max_length=255)
    full_name: str | None = Field(default=None, max_length=255)
    is_active: bool = Field(default=True)
    is_superuser: bool = Field(default=False)


class User(UserBase, table=True):
    """系统用户表。

    当前骨架只实现认证闭环；后续用户管理模块可以继续复用该表。
    """

    __tablename__ = "users"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str = Field(max_length=255)
    created_at: datetime = Field(default_factory=utc_now, nullable=False)
    updated_at: datetime = Field(default_factory=utc_now, nullable=False)
    last_login_at: datetime | None = Field(default=None, nullable=True)
