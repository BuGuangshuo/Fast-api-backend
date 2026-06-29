import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from app.core.consts import AIChatMsg, RedisKey
from app.models import User
from app.schemas import AIChatStreamRequest
from app.services import ai_chat_service
from app.services.ai_chat_service import (
    delete_ai_chat_session_service,
    get_ai_chat_session_service,
    stream_ai_chat_service,
)


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, Any] = {}
        self.ttls: dict[str, int] = {}

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        self.store[key] = value
        self.ttls[key] = ttl or 0
        return True

    async def get(self, key: str) -> Any:
        return self.store.get(key)

    async def delete(self, key: str) -> bool:
        existed = key in self.store
        self.store.pop(key, None)
        self.ttls.pop(key, None)
        return existed

    async def ttl(self, key: str) -> int:
        return self.ttls.get(key, -2)

    async def expire(self, key: str, ttl: int) -> bool:
        if key not in self.store:
            return False
        self.ttls[key] = ttl
        return True


class FakeStreamResponse:
    def __init__(self, lines: list[str], status_code: int = 200) -> None:
        self.lines = lines
        self.status_code = status_code

    async def __aenter__(self) -> "FakeStreamResponse":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def aiter_lines(self) -> AsyncIterator[str]:
        for line in self.lines:
            yield line

    async def aread(self) -> bytes:
        return b"upstream error"


def _user() -> User:
    return User(username="tester", hashed_password="hashed")


async def _collect_stream(
    redis: FakeRedis, user: User, request: AIChatStreamRequest
) -> list[str]:
    return [
        event
        async for event in stream_ai_chat_service(
            redis=redis,
            current_user=user,
            request=request,
        )
    ]


def test_stream_ai_chat_creates_session_and_saves_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_payloads: list[dict[str, Any]] = []
    captured_headers: list[dict[str, str]] = []

    class FakeAsyncClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        def stream(
            self,
            method: str,
            url: str,
            json: dict[str, Any],
            headers: dict[str, str],
        ) -> FakeStreamResponse:
            captured_payloads.append(json)
            captured_headers.append(headers)
            return FakeStreamResponse(
                [
                    'data: {"choices":[{"delta":{"content":"你"}}]}',
                    'data: {"choices":[{"delta":{"content":"好"}}]}',
                    "data: [DONE]",
                ]
            )

    monkeypatch.setattr(ai_chat_service.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(ai_chat_service.settings, "LLM_API_KEY", "test-api-key")
    redis = FakeRedis()
    user = _user()

    events = asyncio.run(
        _collect_stream(redis, user, AIChatStreamRequest(message="你好"))
    )

    assert "event: session" in events[0]
    assert 'event: delta\ndata: {"content": "你"}' in events[1]
    assert 'event: done\ndata: {"session_id":' in events[-1]
    assert captured_payloads[0]["model"] == "Qwen3.5-9B-4bit"
    assert captured_payloads[0]["stream"] is True
    assert captured_payloads[0]["messages"][-1] == {"role": "user", "content": "你好"}
    assert captured_headers[0]["Authorization"] == "Bearer test-api-key"

    assert len(redis.store) == 1
    history = next(iter(redis.store.values()))
    assert history == [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好"},
    ]


def test_stream_ai_chat_uses_existing_session_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_payloads: list[dict[str, Any]] = []

    class FakeAsyncClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        def stream(
            self,
            method: str,
            url: str,
            json: dict[str, Any],
            headers: dict[str, str],
        ) -> FakeStreamResponse:
            captured_payloads.append(json)
            return FakeStreamResponse(
                [
                    'data: {"choices":[{"delta":{"content":"继续"}}]}',
                    "data: [DONE]",
                ]
            )

    monkeypatch.setattr(ai_chat_service.httpx, "AsyncClient", FakeAsyncClient)
    redis = FakeRedis()
    user = _user()
    session_id = "ai_chat_existing"
    redis_key = RedisKey.ai_chat_session(str(user.id), session_id)
    redis.store[redis_key] = [{"role": "assistant", "content": "已有回复"}]

    asyncio.run(
        _collect_stream(
            redis,
            user,
            AIChatStreamRequest(session_id=session_id, message="继续说"),
        )
    )

    assert captured_payloads[0]["messages"] == [
        {"role": "assistant", "content": "已有回复"},
        {"role": "user", "content": "继续说"},
    ]


def test_stream_ai_chat_forwards_thinking_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_payloads: list[dict[str, Any]] = []

    class FakeAsyncClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        def stream(
            self,
            method: str,
            url: str,
            json: dict[str, Any],
            headers: dict[str, str],
        ) -> FakeStreamResponse:
            captured_payloads.append(json)
            return FakeStreamResponse(
                [
                    'data: {"choices":[{"delta":{"content":"ok"}}]}',
                    "data: [DONE]",
                ]
            )

    monkeypatch.setattr(ai_chat_service.httpx, "AsyncClient", FakeAsyncClient)

    asyncio.run(
        _collect_stream(
            FakeRedis(),
            _user(),
            AIChatStreamRequest(message="hello", enable_thinking=False),
        )
    )

    assert captured_payloads[0]["chat_template_kwargs"] == {"enable_thinking": False}


def test_stream_ai_chat_emits_reasoning_when_thinking_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeAsyncClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        def stream(
            self,
            method: str,
            url: str,
            json: dict[str, Any],
            headers: dict[str, str],
        ) -> FakeStreamResponse:
            return FakeStreamResponse(
                [
                    'data: {"choices":[{"delta":{"reasoning_content":"先分析"}}]}',
                    'data: {"choices":[{"delta":{"content":"答案"}}]}',
                    "data: [DONE]",
                ]
            )

    monkeypatch.setattr(ai_chat_service.httpx, "AsyncClient", FakeAsyncClient)
    redis = FakeRedis()

    events = asyncio.run(
        _collect_stream(
            redis,
            _user(),
            AIChatStreamRequest(message="hello", enable_thinking=True),
        )
    )

    assert 'event: reasoning\ndata: {"content": "先分析"}' in events[1]
    assert 'event: delta\ndata: {"content": "答案"}' in events[2]
    assert '"reasoning": "先分析"' in events[-1]

    history = next(iter(redis.store.values()))
    assert history == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "答案"},
    ]


def test_stream_ai_chat_hides_reasoning_when_thinking_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeAsyncClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        def stream(
            self,
            method: str,
            url: str,
            json: dict[str, Any],
            headers: dict[str, str],
        ) -> FakeStreamResponse:
            return FakeStreamResponse(
                [
                    'data: {"choices":[{"delta":{"reasoning_content":"先分析"}}]}',
                    'data: {"choices":[{"delta":{"content":"答案"}}]}',
                    "data: [DONE]",
                ]
            )

    monkeypatch.setattr(ai_chat_service.httpx, "AsyncClient", FakeAsyncClient)

    events = asyncio.run(
        _collect_stream(
            FakeRedis(),
            _user(),
            AIChatStreamRequest(message="hello", enable_thinking=False),
        )
    )

    assert all("event: reasoning" not in event for event in events)
    assert '"reasoning":' not in events[-1]


def test_stream_ai_chat_strips_duplicated_reasoning_from_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeAsyncClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        def stream(
            self,
            method: str,
            url: str,
            json: dict[str, Any],
            headers: dict[str, str],
        ) -> FakeStreamResponse:
            return FakeStreamResponse(
                [
                    'data: {"choices":[{"delta":{"reasoning_content":"先分析"}}]}',
                    'data: {"choices":[{"delta":{"content":"先分析"}}]}',
                    'data: {"choices":[{"delta":{"content":"先分析 最终答案"}}]}',
                    "data: [DONE]",
                ]
            )

    monkeypatch.setattr(ai_chat_service.httpx, "AsyncClient", FakeAsyncClient)

    events = asyncio.run(
        _collect_stream(
            FakeRedis(),
            _user(),
            AIChatStreamRequest(message="hello", enable_thinking=True),
        )
    )

    assert 'event: delta\ndata: {"content": "最终答案"}' in events[2]
    assert '"message": "最终答案"' in events[-1]


def test_stream_ai_chat_returns_error_event_on_upstream_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeAsyncClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        def stream(
            self,
            method: str,
            url: str,
            json: dict[str, Any],
            headers: dict[str, str],
        ) -> FakeStreamResponse:
            return FakeStreamResponse([], status_code=500)

    monkeypatch.setattr(ai_chat_service.httpx, "AsyncClient", FakeAsyncClient)
    redis = FakeRedis()

    events = asyncio.run(
        _collect_stream(redis, _user(), AIChatStreamRequest(message="hello"))
    )

    assert events[-1] == (
        f'event: error\ndata: {{"message": "{AIChatMsg.UPSTREAM_REQUEST_FAILED}"}}\n\n'
    )
    assert redis.store == {}


def test_stream_ai_chat_does_not_save_interrupted_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeAsyncClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        def stream(
            self,
            method: str,
            url: str,
            json: dict[str, Any],
            headers: dict[str, str],
        ) -> FakeStreamResponse:
            return FakeStreamResponse(
                ['data: {"choices":[{"delta":{"content":"半截"}}]}']
            )

    monkeypatch.setattr(ai_chat_service.httpx, "AsyncClient", FakeAsyncClient)
    redis = FakeRedis()

    events = asyncio.run(
        _collect_stream(redis, _user(), AIChatStreamRequest(message="hello"))
    )

    assert 'event: delta\ndata: {"content": "半截"}' in events[1]
    assert events[-1] == (
        f'event: error\ndata: {{"message": "{AIChatMsg.UPSTREAM_REQUEST_FAILED}"}}\n\n'
    )
    assert redis.store == {}


def test_stream_ai_chat_returns_error_event_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeAsyncClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        def stream(
            self,
            method: str,
            url: str,
            json: dict[str, Any],
            headers: dict[str, str],
        ) -> FakeStreamResponse:
            raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(ai_chat_service.httpx, "AsyncClient", FakeAsyncClient)

    events = asyncio.run(
        _collect_stream(FakeRedis(), _user(), AIChatStreamRequest(message="hello"))
    )

    assert events[-1] == (
        f'event: error\ndata: {{"message": "{AIChatMsg.UPSTREAM_TIMEOUT}"}}\n\n'
    )


def test_get_and_delete_ai_chat_session() -> None:
    redis = FakeRedis()
    user = _user()
    session_id = "ai_chat_session"
    redis_key = RedisKey.ai_chat_session(str(user.id), session_id)
    redis.store[redis_key] = [{"role": "user", "content": "hello"}]
    redis.ttls[redis_key] = 60

    response = asyncio.run(
        get_ai_chat_session_service(
            redis=redis,
            current_user=user,
            session_id=session_id,
        )
    )
    assert response.session_id == session_id
    assert response.ttl == 60
    assert response.messages[0].content == "hello"

    message = asyncio.run(
        delete_ai_chat_session_service(
            redis=redis,
            current_user=user,
            session_id=session_id,
        )
    )
    assert message.message == AIChatMsg.SESSION_DELETED
    assert redis.store == {}
