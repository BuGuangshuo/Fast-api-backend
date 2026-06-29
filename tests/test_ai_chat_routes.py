from collections.abc import AsyncIterator
from typing import Any

from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_redis
from app.main import app
from app.models import User
from app.schemas import AIChatStreamRequest


class FakeRedis:
    async def get(self, key: str) -> Any:
        return None


def _user() -> User:
    return User(username="route-user", hashed_password="hashed")


def test_ai_chat_stream_route_requires_login_dependency_override(
    monkeypatch: Any,
) -> None:
    async def fake_current_user() -> User:
        return _user()

    async def fake_redis() -> FakeRedis:
        return FakeRedis()

    async def fake_stream_service(
        *,
        redis: FakeRedis,
        current_user: User,
        request: AIChatStreamRequest,
    ) -> AsyncIterator[str]:
        _ = (redis, current_user, request)
        yield 'event: session\ndata: {"session_id": "ai_chat_test"}\n\n'
        yield 'event: delta\ndata: {"content": "hello"}\n\n'
        yield 'event: done\ndata: {"session_id": "ai_chat_test", "message": "hello"}\n\n'

    monkeypatch.setattr(
        "app.api.routes.ai_chat.stream_ai_chat_service",
        fake_stream_service,
    )
    app.dependency_overrides[get_current_user] = fake_current_user
    app.dependency_overrides[get_redis] = fake_redis
    try:
        client = TestClient(app)
        response = client.post("/api/v1/ai/chat/stream", json={"message": "hello"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: session" in response.text
    assert "event: delta" in response.text
    assert "event: done" in response.text
