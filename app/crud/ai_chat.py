"""AI 对话 CRUD 操作。"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import func
from sqlmodel import Session, col, select

from app.models import AIChatConversation, AIChatConversationMessage, utc_now

AIChatSearchResultType = Literal["conversation", "document"]


@dataclass(frozen=True)
class AIChatHistorySearchMatch:
    """历史对话搜索的内部命中记录。"""

    conversation_id: uuid.UUID
    title: str
    result_type: AIChatSearchResultType
    content: str
    time: datetime


def list_ai_chat_conversations(
    session: Session,
    *,
    user_id: uuid.UUID,
    page: int,
    page_size: int,
) -> tuple[list[AIChatConversation], int]:
    """分页读取当前用户的 AI 对话历史。

    列表始终按 user_id 隔离，不跨用户暴露历史，并按最近消息时间排序。
    """
    base_statement = select(AIChatConversation).where(
        AIChatConversation.user_id == user_id
    )

    total_statement = select(func.count()).select_from(base_statement.subquery())
    total = session.exec(total_statement).one()

    # 历史对话按最近消息时间倒序展示，稳定兜底到创建时间。
    statement = (
        base_statement.order_by(
            col(AIChatConversation.last_message_at).desc(),
            col(AIChatConversation.created_at).desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(session.exec(statement).all()), int(total or 0)


def search_ai_chat_history(
    session: Session,
    *,
    user_id: uuid.UUID,
    keyword: str,
    result_type: AIChatSearchResultType | None,
    page: int,
    page_size: int,
) -> tuple[list[AIChatHistorySearchMatch], int]:
    """搜索当前用户的会话文字、标题和附件文件名，并分页返回命中项。

    附件元数据存储在 JSON 数组中。当前系统规模较小，因此先按用户一次读取会话消息，
    再精确检查 filename，避免把 MIME 类型或其他附件元数据误判为文档名命中。
    """
    statement = (
        select(AIChatConversation, AIChatConversationMessage)
        .join(
            AIChatConversationMessage,
            col(AIChatConversationMessage.conversation_id)
            == col(AIChatConversation.id),
        )
        .where(AIChatConversation.user_id == user_id)
        .order_by(col(AIChatConversationMessage.created_at).desc())
    )
    rows = session.exec(statement).all()
    normalized_keyword = keyword.casefold()
    matches: list[AIChatHistorySearchMatch] = []
    matched_conversation_ids: set[uuid.UUID] = set()
    matched_documents: set[tuple[uuid.UUID, str]] = set()

    # 每个会话最多返回一个 conversation 命中，优先展示最新命中的消息正文。
    if result_type in {None, "conversation"}:
        for conversation, message in rows:
            if conversation.id in matched_conversation_ids:
                continue
            title_matched = normalized_keyword in conversation.title.casefold()
            content_matched = normalized_keyword in message.content.casefold()
            if not title_matched and not content_matched:
                continue
            matches.append(
                AIChatHistorySearchMatch(
                    conversation_id=conversation.id,
                    title=conversation.title,
                    result_type="conversation",
                    content=message.content if content_matched else conversation.title,
                    time=(
                        message.created_at
                        if content_matched
                        else conversation.last_message_at
                    ),
                )
            )
            matched_conversation_ids.add(conversation.id)

    # 同一会话内同名文档只返回一次，时间取最近一次上传该文档的消息时间。
    if result_type in {None, "document"}:
        for conversation, message in rows:
            for attachment in message.attachments:
                filename = attachment.get("filename")
                if not isinstance(filename, str):
                    continue
                document_key = (conversation.id, filename.casefold())
                if (
                    normalized_keyword not in filename.casefold()
                    or document_key in matched_documents
                ):
                    continue
                matches.append(
                    AIChatHistorySearchMatch(
                        conversation_id=conversation.id,
                        title=conversation.title,
                        result_type="document",
                        content=filename,
                        time=message.created_at,
                    )
                )
                matched_documents.add(document_key)

    matches.sort(key=lambda match: match.time, reverse=True)
    total = len(matches)
    offset = (page - 1) * page_size
    return matches[offset : offset + page_size], total


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


def create_ai_chat_conversation(
    session: Session,
    *,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    title: str,
) -> AIChatConversation:
    """先创建可恢复生成的会话占位，使生成期间也能出现在最近对话中。"""
    now = utc_now()
    conversation = AIChatConversation(
        id=conversation_id,
        user_id=user_id,
        title=title,
        created_at=now,
        updated_at=now,
        last_message_at=now,
    )
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    return conversation


def append_ai_chat_user_message(
    session: Session,
    *,
    conversation: AIChatConversation,
    content: str,
    attachments: list[dict[str, Any]] | None = None,
) -> AIChatConversationMessage:
    """在后台生成入队前写入用户消息，确保刷新时问题已经可恢复。"""
    now = utc_now()
    message = AIChatConversationMessage(
        conversation_id=conversation.id,
        role="user",
        content=content,
        attachments=attachments or [],
        sort_order=_next_message_sort_order(
            session,
            conversation_id=conversation.id,
        ),
        created_at=now,
    )
    conversation.updated_at = now
    conversation.last_message_at = now
    session.add(conversation)
    session.add(message)
    session.commit()
    session.refresh(message)
    return message


def append_ai_chat_assistant_message(
    session: Session,
    *,
    conversation: AIChatConversation,
    content: str,
    reasoning_content: str | None = None,
) -> AIChatConversationMessage:
    """在后台生成结束或停止后，追加对应的 assistant 消息。"""
    now = utc_now()
    message = AIChatConversationMessage(
        conversation_id=conversation.id,
        role="assistant",
        content=content,
        reasoning_content=reasoning_content,
        sort_order=_next_message_sort_order(
            session,
            conversation_id=conversation.id,
        ),
        created_at=now,
    )
    conversation.updated_at = now
    conversation.last_message_at = now
    session.add(conversation)
    session.add(message)
    session.commit()
    session.refresh(message)
    return message


def append_ai_chat_exchange(
    session: Session,
    *,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    title: str,
    user_message: str,
    assistant_message: str,
    user_attachments: list[dict[str, Any]] | None = None,
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
            attachments=user_attachments or [],
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
