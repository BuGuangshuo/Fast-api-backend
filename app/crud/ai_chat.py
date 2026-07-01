"""AI 对话 CRUD 操作。"""

import uuid

from sqlalchemy import func
from sqlmodel import Session, col, select

from app.models import AIChatConversation, AIChatConversationMessage, utc_now


def list_ai_chat_conversations(
    session: Session,
    *,
    user_id: uuid.UUID,
    page: int,
    page_size: int,
) -> tuple[list[AIChatConversation], int]:
    """分页读取当前用户的 AI 对话最近列表。

    列表只按 user_id 隔离，不跨用户暴露历史；排序使用最近消息时间支撑最近栏展示。
    """
    base_statement = select(AIChatConversation).where(
        AIChatConversation.user_id == user_id
    )
    total_statement = select(func.count()).select_from(base_statement.subquery())
    total = session.exec(total_statement).one()

    # 最近栏按最近消息时间倒序展示，稳定兜底到创建时间。
    statement = (
        base_statement.order_by(
            col(AIChatConversation.last_message_at).desc(),
            col(AIChatConversation.created_at).desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(session.exec(statement).all()), int(total or 0)


def get_ai_chat_conversation_for_user(
    session: Session,
    *,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
) -> AIChatConversation | None:
    """按会话 ID 和用户 ID 读取会话，用于权限隔离。"""
    statement = select(AIChatConversation).where(
        AIChatConversation.id == conversation_id,
        AIChatConversation.user_id == user_id,
    )
    return session.exec(statement).first()


def list_ai_chat_messages(
    session: Session,
    *,
    conversation_id: uuid.UUID,
) -> list[AIChatConversationMessage]:
    """读取会话完整消息历史，按写入顺序稳定回放。"""
    statement = (
        select(AIChatConversationMessage)
        .where(AIChatConversationMessage.conversation_id == conversation_id)
        .order_by(
            col(AIChatConversationMessage.sort_order).asc(),
            col(AIChatConversationMessage.created_at).asc(),
        )
    )
    return list(session.exec(statement).all())


def _next_message_sort_order(
    session: Session,
    *,
    conversation_id: uuid.UUID,
) -> int:
    """计算下一条消息序号，低并发本地工具场景下用聚合查询即可。"""
    statement = select(func.max(AIChatConversationMessage.sort_order)).where(
        AIChatConversationMessage.conversation_id == conversation_id
    )
    max_order = session.exec(statement).one()
    return int(max_order or 0) + 1


def append_ai_chat_exchange(
    session: Session,
    *,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    title: str,
    user_message: str,
    assistant_message: str,
    reasoning_content: str | None = None,
) -> AIChatConversation:
    """写入一轮完整 user / assistant 问答。

    如果会话不存在则创建会话；如果已存在则仅追加消息并刷新最近消息时间。
    """
    now = utc_now()
    conversation = get_ai_chat_conversation_for_user(
        session,
        conversation_id=conversation_id,
        user_id=user_id,
    )
    if conversation is None:
        conversation = AIChatConversation(
            id=conversation_id,
            user_id=user_id,
            title=title,
            created_at=now,
            updated_at=now,
            last_message_at=now,
        )
        session.add(conversation)
        next_order = 1
    else:
        conversation.updated_at = now
        conversation.last_message_at = now
        session.add(conversation)
        next_order = _next_message_sort_order(
            session,
            conversation_id=conversation_id,
        )

    session.add(
        AIChatConversationMessage(
            conversation_id=conversation_id,
            role="user",
            content=user_message,
            sort_order=next_order,
            created_at=now,
        )
    )
    session.add(
        AIChatConversationMessage(
            conversation_id=conversation_id,
            role="assistant",
            content=assistant_message,
            reasoning_content=reasoning_content,
            sort_order=next_order + 1,
            created_at=now,
        )
    )
    session.commit()
    session.refresh(conversation)
    return conversation


def update_ai_chat_conversation_title(
    session: Session,
    *,
    conversation: AIChatConversation,
    title: str,
) -> AIChatConversation:
    """更新会话标题。"""
    conversation.title = title
    conversation.updated_at = utc_now()
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    return conversation


def delete_ai_chat_conversation(
    session: Session,
    *,
    conversation: AIChatConversation,
) -> None:
    """删除会话及其消息历史。"""
    for message in list_ai_chat_messages(session, conversation_id=conversation.id):
        session.delete(message)
    session.delete(conversation)
    session.commit()
