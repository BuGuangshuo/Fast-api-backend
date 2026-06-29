"""AI 对话 Service。"""

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import HTTPException, status
from pydantic import ValidationError

from app.core.config import settings
from app.core.consts import AIChatMsg, RedisKey
from app.core.redis import RedisService
from app.models import User
from app.schemas import (
    AIChatMessage,
    AIChatSessionResponse,
    AIChatStreamRequest,
    Message,
)
from app.utils import get_logger

logger = get_logger(__name__)


class _AIChatUpstreamError(Exception):
    """可转换为 SSE error 事件的上游错误。"""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def _new_session_id() -> str:
    return f"ai_chat_{uuid.uuid4().hex}"


def _session_ttl() -> int:
    return max(settings.LLM_CHAT_SESSION_TTL_SECONDS, 1)


def _history_limit() -> int:
    return max(settings.LLM_CHAT_MAX_HISTORY_MESSAGES, 2)


def _session_key(user: User, session_id: str) -> str:
    return RedisKey.ai_chat_session(str(user.id), session_id)


def _sse_event(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def _coerce_messages(value: Any) -> list[AIChatMessage]:
    """从 Redis 值恢复消息列表，跳过异常历史项避免单条脏数据拖垮会话。"""
    if not isinstance(value, list):
        return []

    messages: list[AIChatMessage] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            messages.append(AIChatMessage.model_validate(item))
        except ValidationError:
            logger.warning("忽略异常 AI 对话历史项: %s", item)
    return messages


async def _load_history(redis: RedisService, key: str) -> list[AIChatMessage]:
    cached_value = await redis.get(key)
    if cached_value is None:
        return []
    return _coerce_messages(cached_value)


def _trim_history(messages: list[AIChatMessage]) -> list[AIChatMessage]:
    return messages[-_history_limit() :]


async def _save_history(
    *,
    redis: RedisService,
    key: str,
    history: list[AIChatMessage],
    user_message: str,
    assistant_message: str,
) -> None:
    """完整流式响应结束后再写入 Redis，避免保存半截 assistant 回复。"""
    if not assistant_message:
        return

    next_history = _trim_history(
        [
            *history,
            AIChatMessage(role="user", content=user_message),
            AIChatMessage(role="assistant", content=assistant_message),
        ]
    )
    await redis.set(
        key,
        [message.model_dump() for message in next_history],
        _session_ttl(),
    )


def _request_messages(
    history: list[AIChatMessage], request: AIChatStreamRequest
) -> list[dict[str, str]]:
    messages: list[AIChatMessage] = []
    if request.system_prompt and request.system_prompt.strip():
        messages.append(
            AIChatMessage(role="system", content=request.system_prompt.strip())
        )
    messages.extend(_trim_history(history))
    messages.append(AIChatMessage(role="user", content=request.message))
    return [{"role": message.role, "content": message.content} for message in messages]


def _openai_payload(
    history: list[AIChatMessage], request: AIChatStreamRequest
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": request.model or settings.LLM_CHAT_MODEL,
        "messages": _request_messages(history, request),
        "stream": True,
    }
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.max_tokens is not None:
        payload["max_tokens"] = request.max_tokens
    if request.enable_thinking is not None:
        payload["chat_template_kwargs"] = {"enable_thinking": request.enable_thinking}
    return payload


def _openai_headers() -> dict[str, str]:
    headers = {
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
    }
    api_key = settings.LLM_API_KEY.strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _extract_delta(raw_line: str) -> tuple[str | None, str | None]:
    try:
        payload = json.loads(raw_line)
    except json.JSONDecodeError:
        raise _AIChatUpstreamError(AIChatMsg.UPSTREAM_RESPONSE_INVALID)

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None, None
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return None, None
    delta = first_choice.get("delta")
    if not isinstance(delta, dict):
        return None, None

    content = delta.get("content")
    if not isinstance(content, str) or not content:
        content = None

    reasoning_content = delta.get("reasoning_content")
    if not isinstance(reasoning_content, str) or not reasoning_content:
        reasoning_content = None

    return content, reasoning_content


def _strip_duplicated_reasoning(content: str, reasoning_content: str) -> str | None:
    """oMLX 截断思考块时可能把已流出的 reasoning 再作为 content 返回。"""
    if not reasoning_content:
        return content
    if reasoning_content.startswith(content):
        return None
    if content.startswith(reasoning_content):
        answer_content = content[len(reasoning_content) :].lstrip()
        return answer_content or None
    return content


async def _iter_openai_deltas(
    payload: dict[str, Any],
) -> AsyncIterator[tuple[str, str]]:
    timeout = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)
    url = f"{settings.LLM_API_BASE_URL.rstrip('/')}/chat/completions"

    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST",
            url,
            json=payload,
            headers=_openai_headers(),
        ) as response:
            if response.status_code >= status.HTTP_400_BAD_REQUEST:
                await response.aread()
                raise _AIChatUpstreamError(AIChatMsg.UPSTREAM_REQUEST_FAILED)

            completed = False
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw_line = line.removeprefix("data:").strip()
                if not raw_line:
                    continue
                if raw_line == "[DONE]":
                    completed = True
                    break
                content, reasoning_content = _extract_delta(raw_line)
                if reasoning_content is not None:
                    yield "reasoning", reasoning_content
                if content is not None:
                    yield "delta", content
            if not completed:
                raise _AIChatUpstreamError(AIChatMsg.UPSTREAM_REQUEST_FAILED)


async def stream_ai_chat_service(
    *, redis: RedisService, current_user: User, request: AIChatStreamRequest
) -> AsyncIterator[str]:
    """代理 OpenAI-compatible 流式对话。

    1. 确定或创建当前用户隔离的临时会话
    2. 从 Redis 读取历史并构造 OpenAI-compatible 请求
    3. 将上游 data chunk 转换为前端 SSE 事件
    4. 上游完整结束后再写回 user / assistant 历史
    """
    session_id = request.session_id or _new_session_id()
    redis_key = _session_key(current_user, session_id)
    history = await _load_history(redis, redis_key)
    payload = _openai_payload(history, request)
    assistant_chunks: list[str] = []
    reasoning_chunks: list[str] = []

    yield _sse_event("session", {"session_id": session_id})

    try:
        async for event, delta in _iter_openai_deltas(payload):
            if event == "reasoning":
                if request.enable_thinking is True:
                    reasoning_chunks.append(delta)
                    yield _sse_event("reasoning", {"content": delta})
                continue

            if request.enable_thinking is True:
                stripped_delta = _strip_duplicated_reasoning(
                    delta, "".join(reasoning_chunks)
                )
                if stripped_delta is None:
                    continue
                delta = stripped_delta

            assistant_chunks.append(delta)
            yield _sse_event("delta", {"content": delta})
    except httpx.TimeoutException:
        logger.exception("AI 服务响应超时")
        yield _sse_event("error", {"message": AIChatMsg.UPSTREAM_TIMEOUT})
        return
    except httpx.HTTPError:
        logger.exception("AI 服务请求异常")
        yield _sse_event("error", {"message": AIChatMsg.UPSTREAM_REQUEST_FAILED})
        return
    except _AIChatUpstreamError as exc:
        logger.warning("AI 服务响应异常: %s", exc.message)
        yield _sse_event("error", {"message": exc.message})
        return

    assistant_message = "".join(assistant_chunks)
    await _save_history(
        redis=redis,
        key=redis_key,
        history=history,
        user_message=request.message,
        assistant_message=assistant_message,
    )
    done_data = {"session_id": session_id, "message": assistant_message}
    if request.enable_thinking is True:
        done_data["reasoning"] = "".join(reasoning_chunks)
    yield _sse_event("done", done_data)


async def get_ai_chat_session_service(
    *, redis: RedisService, current_user: User, session_id: str
) -> AIChatSessionResponse:
    """读取当前登录用户的 AI 对话临时历史。"""
    redis_key = _session_key(current_user, session_id)
    cached_value = await redis.get(redis_key)
    if cached_value is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AIChatMsg.SESSION_NOT_FOUND,
        )

    return AIChatSessionResponse(
        session_id=session_id,
        messages=_coerce_messages(cached_value),
        ttl=await redis.ttl(redis_key),
    )


async def delete_ai_chat_session_service(
    *, redis: RedisService, current_user: User, session_id: str
) -> Message:
    """删除当前登录用户的 AI 对话临时历史。"""
    redis_key = _session_key(current_user, session_id)
    if not await redis.delete(redis_key):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AIChatMsg.SESSION_NOT_FOUND,
        )
    return Message(message=AIChatMsg.SESSION_DELETED)
