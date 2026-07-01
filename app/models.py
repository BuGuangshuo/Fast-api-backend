"""SQLModel ORM models.

所有 ORM 模型集中放在本文件，后续业务模块继续按分区追加。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, Text
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


# ==================== AI Chat ====================


class AIChatConversationBase(SQLModel):
    """AI 对话会话基础字段，用于最近栏展示和会话归属校验。"""

    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    title: str = Field(index=True, max_length=128)


class AIChatConversation(AIChatConversationBase, table=True):
    """AI 对话持久化会话表。

    会话名称可自动生成，也可由用户手动重命名；列表按最近消息时间倒序展示。
    """

    __tablename__ = "ai_chat_conversations"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime = Field(default_factory=utc_now, nullable=False)
    updated_at: datetime = Field(default_factory=utc_now, nullable=False)
    last_message_at: datetime = Field(
        default_factory=utc_now, index=True, nullable=False
    )


class AIChatConversationMessageBase(SQLModel):
    """AI 对话消息基础字段，仅保存问答正文，不持久化本轮附件内容。"""

    conversation_id: uuid.UUID = Field(
        foreign_key="ai_chat_conversations.id",
        index=True,
    )
    role: str = Field(max_length=16)
    content: str = Field(sa_column=Column(Text, nullable=False))
    reasoning_content: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    sort_order: int = Field(index=True)


class AIChatConversationMessage(AIChatConversationMessageBase, table=True):
    """AI 对话消息表。

    sort_order 保证同一会话内 user / assistant 消息按写入顺序稳定回放。
    """

    __tablename__ = "ai_chat_messages"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime = Field(default_factory=utc_now, nullable=False)
