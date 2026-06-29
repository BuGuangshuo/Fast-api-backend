"""AI 对话路由。"""

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser, RedisDep
from app.schemas import AIChatSessionResponse, AIChatStreamRequest, Message
from app.services.ai_chat_service import (
    delete_ai_chat_session_service,
    get_ai_chat_session_service,
    stream_ai_chat_service,
)

router = APIRouter(prefix="/ai", tags=["ai-chat"])


@router.post("/chat/stream")
async def stream_ai_chat(
    *,
    redis: RedisDep,
    current_user: CurrentUser,
    request: AIChatStreamRequest,
) -> StreamingResponse:
    """发起受登录保护的流式 AI 对话。"""
    return StreamingResponse(
        stream_ai_chat_service(
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


@router.get("/chat/sessions/{session_id}", response_model=AIChatSessionResponse)
async def get_ai_chat_session(
    *,
    redis: RedisDep,
    current_user: CurrentUser,
    session_id: str,
) -> AIChatSessionResponse:
    """读取当前用户的 AI 对话临时会话历史。"""
    return await get_ai_chat_session_service(
        redis=redis,
        current_user=current_user,
        session_id=session_id,
    )


@router.delete("/chat/sessions/{session_id}", response_model=Message)
async def delete_ai_chat_session(
    *,
    redis: RedisDep,
    current_user: CurrentUser,
    session_id: str,
) -> Message:
    """删除当前用户的 AI 对话临时会话历史。"""
    return await delete_ai_chat_session_service(
        redis=redis,
        current_user=current_user,
        session_id=session_id,
    )
