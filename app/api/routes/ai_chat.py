"""AI 对话路由。"""

import json
import uuid

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from app.api.deps import CurrentUser, RedisDep, SessionDep
from app.core.consts import AIChatMsg
from app.schemas import (
    AIChatConversationListItem,
    AIChatConversationResponse,
    AIChatConversationUpdateRequest,
    AIChatSearchResultItem,
    AIChatSearchType,
    AIChatSessionResponse,
    AIChatStreamRequest,
    Message,
    PaginatedResponse,
)
from app.services.ai_chat_service import (
    build_ai_chat_stream_request_from_multipart,
    delete_ai_chat_conversation_service,
    delete_ai_chat_session_service,
    get_ai_chat_conversation_service,
    get_ai_chat_session_service,
    list_ai_chat_conversations_service,
    search_ai_chat_history_service,
    stream_ai_chat_service,
    update_ai_chat_conversation_title_service,
)

router = APIRouter(prefix="/ai", tags=["ai-chat"])


async def _parse_stream_request(http_request: Request) -> AIChatStreamRequest:
    """兼容 JSON 与 multipart/form-data 两种 AI 对话提交方式。"""
    content_type = http_request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await http_request.form()
        return await build_ai_chat_stream_request_from_multipart(form)

    try:
        payload = await http_request.json()
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AIChatMsg.REQUEST_BODY_INVALID,
        )
    try:
        return AIChatStreamRequest.model_validate(payload)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc


@router.post("/chat/stream")
async def stream_ai_chat(
    *,
    session: SessionDep,
    redis: RedisDep,
    current_user: CurrentUser,
    http_request: Request,
) -> StreamingResponse:
    """发起受登录保护的流式 AI 对话，支持 JSON 或带附件表单。"""
    request = await _parse_stream_request(http_request)
    return StreamingResponse(
        stream_ai_chat_service(
            session=session,
            redis=redis,
            current_user=current_user,
            request=request,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/chat/conversations",
    response_model=PaginatedResponse[AIChatConversationListItem],
)
def list_ai_chat_conversations(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(
        default=8,
        ge=1,
        le=100,
        alias="pageSize",
        description="每页数量",
    ),
) -> PaginatedResponse[AIChatConversationListItem]:
    """分页读取当前用户 AI 对话历史。"""
    return list_ai_chat_conversations_service(
        session=session,
        current_user=current_user,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/chat/conversations/search",
    response_model=PaginatedResponse[AIChatSearchResultItem],
)
def search_ai_chat_history(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    keyword: str = Query(
        min_length=1,
        max_length=128,
        pattern=r".*\S.*",
        description="对话文字、会话标题或历史文档名关键词",
    ),
    result_type: AIChatSearchType | None = Query(
        default=None,
        alias="type",
        description="结果类型；不传则返回 conversation 和 document",
    ),
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(
        default=8,
        ge=1,
        le=100,
        alias="pageSize",
        description="每页数量",
    ),
) -> PaginatedResponse[AIChatSearchResultItem]:
    """模糊搜索当前用户的历史对话文字和已上传文档名。"""
    return search_ai_chat_history_service(
        session=session,
        current_user=current_user,
        keyword=keyword,
        result_type=result_type,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/chat/conversations/{conversation_id}",
    response_model=AIChatConversationResponse,
)
def get_ai_chat_conversation(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    conversation_id: uuid.UUID,
) -> AIChatConversationResponse:
    """读取当前用户 AI 对话完整历史。"""
    return get_ai_chat_conversation_service(
        session=session,
        current_user=current_user,
        conversation_id=conversation_id,
    )


@router.patch(
    "/chat/conversations/{conversation_id}",
    response_model=AIChatConversationResponse,
)
def update_ai_chat_conversation_title(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    conversation_id: uuid.UUID,
    request: AIChatConversationUpdateRequest,
) -> AIChatConversationResponse:
    """修改当前用户 AI 对话会话名称。"""
    return update_ai_chat_conversation_title_service(
        session=session,
        current_user=current_user,
        conversation_id=conversation_id,
        title=request.title,
    )


@router.delete("/chat/conversations/{conversation_id}", response_model=Message)
def delete_ai_chat_conversation(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    conversation_id: uuid.UUID,
) -> Message:
    """删除当前用户 AI 对话会话历史。"""
    return delete_ai_chat_conversation_service(
        session=session,
        current_user=current_user,
        conversation_id=conversation_id,
    )


@router.get("/chat/sessions/{session_id}", response_model=AIChatSessionResponse)
async def get_ai_chat_session(
    *,
    session: SessionDep,
    redis: RedisDep,
    current_user: CurrentUser,
    session_id: str,
) -> AIChatSessionResponse:
    """读取当前用户的 AI 对话临时会话历史。"""
    return await get_ai_chat_session_service(
        session=session,
        redis=redis,
        current_user=current_user,
        session_id=session_id,
    )


@router.delete("/chat/sessions/{session_id}", response_model=Message)
async def delete_ai_chat_session(
    *,
    session: SessionDep,
    redis: RedisDep,
    current_user: CurrentUser,
    session_id: str,
) -> Message:
    """删除当前用户的 AI 对话临时会话历史。"""
    return await delete_ai_chat_session_service(
        session=session,
        redis=redis,
        current_user=current_user,
        session_id=session_id,
    )
