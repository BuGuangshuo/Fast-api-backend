"""可恢复 AI 对话 Celery 任务。"""

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import suppress
from typing import Any, cast

from pydantic import ValidationError
from sqlmodel import Session

from app import crud
from app.core.celery_app import celery_app
from app.core.consts import AIChatMsg, RedisKey
from app.core.db import engine
from app.core.redis import RedisService, redis_manager
from app.schemas import AIChatStreamRequest
from app.services.ai_chat_service import stream_ai_chat_service
from app.utils import get_logger

logger = get_logger(__name__)


def _parse_sse_event(raw_event: str) -> tuple[str, dict[str, Any]] | None:
    """解析内部 SSE 文本，供 worker 写回可恢复生成快照。"""
    event_name: str | None = None
    data_text: str | None = None
    for line in raw_event.splitlines():
        if line.startswith("event: "):
            event_name = line.removeprefix("event: ")
        elif line.startswith("data: "):
            data_text = line.removeprefix("data: ")
    if event_name is None or data_text is None:
        return None
    try:
        payload = json.loads(data_text)
    except json.JSONDecodeError:
        return None
    return (event_name, payload) if isinstance(payload, dict) else None


async def _save_generation_value(
    *,
    redis: RedisService,
    key: str,
    cancelled_key: str,
    value: dict[str, Any],
    ttl: int,
) -> bool:
    """刷新生成快照；若用户已取消，则固定 cancelled 终态并停止后续消费。"""
    if await redis.get(cancelled_key):
        value["status"] = "cancelled"
        value["error"] = None
        value["revision"] = int(value.get("revision", 0)) + 1
        await redis.set(key, value, ttl)
        return False

    value["revision"] = int(value.get("revision", 0)) + 1
    await redis.set(key, value, ttl)
    if not await redis.get(cancelled_key):
        return True

    # 取消请求可能与本次写入并发；写入后再确认一次，避免旧状态覆盖 cancelled。
    value["status"] = "cancelled"
    value["error"] = None
    value["revision"] = int(value.get("revision", 0)) + 1
    await redis.set(key, value, ttl)
    return False


async def _stream_until_generation_cancelled(
    *,
    stream: AsyncGenerator[str, None],
    redis: RedisService,
    cancelled_key: str,
) -> AsyncIterator[str]:
    """轮询取消标记，并在用户停止时主动关闭仍在等待上游数据的生成流。"""

    async def read_next_event() -> str:
        return await stream.__anext__()

    pending_event: asyncio.Task[str] = asyncio.create_task(read_next_event())
    try:
        while True:
            completed, _ = await asyncio.wait(
                {pending_event},
                timeout=0.2,
            )
            if pending_event in completed:
                try:
                    raw_event = pending_event.result()
                except StopAsyncIteration:
                    return
                yield raw_event
                pending_event = asyncio.create_task(read_next_event())
                continue

            if await redis.get(cancelled_key):
                return
    finally:
        pending_event.cancel()
        with suppress(asyncio.CancelledError, StopAsyncIteration):
            await pending_event
        await stream.aclose()


async def _run_ai_chat_generation(generation_id: str, user_id: str) -> None:
    """执行可恢复 AI 回答。

    每个 Celery 任务在自己的 asyncio.run() 事件循环中初始化并关闭 Redis，
    避免后续任务复用绑定到已关闭事件循环的连接。
    """
    if redis_manager.redis_client is None:
        await redis_manager.init_redis()
    if redis_manager.redis_client is None:
        raise RuntimeError("Redis client is not initialized")

    redis = RedisService(redis_manager.redis_client)
    try:
        await _execute_ai_chat_generation(
            generation_id=generation_id,
            user_id=user_id,
            redis=redis,
        )
    finally:
        await redis_manager.close_redis()


async def _execute_ai_chat_generation(
    *,
    generation_id: str,
    user_id: str,
    redis: RedisService,
) -> None:
    """恢复请求并消费模型 SSE，将实时内容和终态持续写回 Redis。"""
    generation_key = RedisKey.ai_chat_generation(user_id, generation_id)
    request_key = RedisKey.ai_chat_generation_request(user_id, generation_id)
    cancelled_key = RedisKey.ai_chat_generation_cancelled(user_id, generation_id)
    raw_value = await redis.get(generation_key)
    raw_request = await redis.get(request_key)
    if not isinstance(raw_value, dict) or not isinstance(raw_request, dict):
        logger.warning("AI 生成任务快照不存在或已过期: %s", generation_id)
        return

    value = raw_value
    ttl = max(await redis.ttl(generation_key), 1)
    try:
        request = AIChatStreamRequest.model_validate(raw_request)
        parsed_user_id = uuid.UUID(user_id)
    except (ValidationError, ValueError):
        value["status"] = "failed"
        value["error"] = AIChatMsg.REQUEST_BODY_INVALID
        await _save_generation_value(
            redis=redis,
            key=generation_key,
            cancelled_key=cancelled_key,
            value=value,
            ttl=ttl,
        )
        return

    with Session(engine) as session:
        user = crud.get_user_by_id(session, parsed_user_id)
        if user is None:
            value["status"] = "failed"
            value["error"] = AIChatMsg.SESSION_NOT_FOUND
            await _save_generation_value(
                redis=redis,
                key=generation_key,
                cancelled_key=cancelled_key,
                value=value,
                ttl=ttl,
            )
            return

        value["status"] = "thinking"
        should_continue = await _save_generation_value(
            redis=redis,
            key=generation_key,
            cancelled_key=cancelled_key,
            value=value,
            ttl=ttl,
        )
        if not should_continue:
            await redis.delete(request_key)
            return

        terminal_event_received = False
        try:
            upstream_stream = cast(
                AsyncGenerator[str, None],
                stream_ai_chat_service(
                    session=session,
                    redis=redis,
                    current_user=user,
                    request=request,
                    user_message_persisted=True,
                ),
            )
            async for raw_event in _stream_until_generation_cancelled(
                stream=upstream_stream,
                redis=redis,
                cancelled_key=cancelled_key,
            ):
                parsed_event = _parse_sse_event(raw_event)
                if parsed_event is None:
                    continue
                event_name, payload = parsed_event

                if event_name == "title":
                    title = payload.get("title")
                    if isinstance(title, str):
                        value["title"] = title
                        conversation_id = uuid.UUID(value["session_id"])
                        conversation = crud.get_ai_chat_conversation_for_user(
                            session,
                            conversation_id=conversation_id,
                            user_id=user.id,
                        )
                        if conversation is not None:
                            crud.update_ai_chat_conversation_title(
                                session,
                                conversation=conversation,
                                title=title,
                            )
                elif event_name == "reasoning":
                    delta = payload.get("content")
                    if isinstance(delta, str):
                        value["status"] = "thinking"
                        value["reasoning_content"] = (
                            str(value.get("reasoning_content", "")) + delta
                        )
                elif event_name == "delta":
                    delta = payload.get("content")
                    if isinstance(delta, str):
                        value["status"] = "answering"
                        value["content"] = str(value.get("content", "")) + delta
                elif event_name == "done":
                    value["status"] = "completed"
                    value["error"] = None
                    terminal_event_received = True
                elif event_name == "error":
                    value["status"] = "failed"
                    message = payload.get("message")
                    value["error"] = (
                        message
                        if isinstance(message, str)
                        else AIChatMsg.UPSTREAM_REQUEST_FAILED
                    )
                    terminal_event_received = True

                should_continue = await _save_generation_value(
                    redis=redis,
                    key=generation_key,
                    cancelled_key=cancelled_key,
                    value=value,
                    ttl=ttl,
                )
                if not should_continue:
                    terminal_event_received = True
                    break
        except Exception:
            logger.exception("AI 生成过程中发生未处理异常: %s", generation_id)

        if await redis.get(cancelled_key):
            terminal_event_received = True
            value["status"] = "cancelled"
            value["error"] = None

        if not terminal_event_received:
            value["status"] = "failed"
            value["error"] = AIChatMsg.UPSTREAM_REQUEST_FAILED
            await _save_generation_value(
                redis=redis,
                key=generation_key,
                cancelled_key=cancelled_key,
                value=value,
                ttl=ttl,
            )

    await redis.delete(request_key)


@celery_app.task(name="app.tasks.ai_chat.generate_ai_chat_response_task")
def generate_ai_chat_response_task(generation_id: str, user_id: str) -> None:
    """在 Celery worker 中完成回答，浏览器断连不会取消该任务。

    任务边界保持同步，通过 asyncio.run() 桥接现有 async Redis 与模型调用；
    错误写入生成快照，不启用自动重试，避免同一用户问题生成两份回答。
    """
    try:
        asyncio.run(_run_ai_chat_generation(generation_id, user_id))
    except Exception:
        logger.exception("可恢复 AI 对话任务执行失败: %s", generation_id)
