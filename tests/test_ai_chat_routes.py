import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.api.deps import get_current_user, get_db, get_redis
from app.main import app
from app.models import User
from app.schemas import AIChatStreamRequest


class FakeRedis:
    async def get(self, key: str) -> Any:
        return None


def _user() -> User:
    return User(username="route-user", hashed_password="hashed")


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_ai_chat_stream_route_requires_login_dependency_override(
    monkeypatch: Any,
) -> None:
    async def fake_current_user() -> User:
        return _user()

    async def fake_redis() -> FakeRedis:
        return FakeRedis()

    def fake_db() -> Session:
        return _session()

    async def fake_stream_service(
        *,
        session: Session,
        redis: FakeRedis,
        current_user: User,
        request: AIChatStreamRequest,
    ) -> AsyncIterator[str]:
        _ = (session, redis, current_user, request)
        yield 'event: session\ndata: {"session_id": "ai_chat_test"}\n\n'
        yield 'event: delta\ndata: {"content": "hello"}\n\n'
        yield 'event: done\ndata: {"session_id": "ai_chat_test", "message": "hello"}\n\n'

    monkeypatch.setattr(
        "app.api.routes.ai_chat.stream_ai_chat_service",
        fake_stream_service,
    )
    app.dependency_overrides[get_current_user] = fake_current_user
    app.dependency_overrides[get_redis] = fake_redis
    app.dependency_overrides[get_db] = fake_db
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


def test_ai_chat_stream_route_accepts_multipart_files(monkeypatch: Any) -> None:
    captured_requests: list[AIChatStreamRequest] = []

    async def fake_current_user() -> User:
        return _user()

    async def fake_redis() -> FakeRedis:
        return FakeRedis()

    def fake_db() -> Session:
        return _session()

    async def fake_stream_service(
        *,
        session: Session,
        redis: FakeRedis,
        current_user: User,
        request: AIChatStreamRequest,
    ) -> AsyncIterator[str]:
        _ = (session, redis, current_user)
        captured_requests.append(request)
        yield 'event: session\ndata: {"session_id": "ai_chat_test"}\n\n'
        yield 'event: done\ndata: {"session_id": "ai_chat_test", "message": "ok"}\n\n'

    monkeypatch.setattr(
        "app.api.routes.ai_chat.stream_ai_chat_service",
        fake_stream_service,
    )
    app.dependency_overrides[get_current_user] = fake_current_user
    app.dependency_overrides[get_redis] = fake_redis
    app.dependency_overrides[get_db] = fake_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/ai/chat/stream",
            data={
                "message": "分析附件",
                "relative_paths": '["folder/a.txt"]',
            },
            files={
                "files": ("a.txt", b"hello", "text/plain"),
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert captured_requests[0].message == "分析附件"
    assert captured_requests[0].attachments[0].filename == "folder/a.txt"
    assert captured_requests[0].attachments[0].text == "hello"


def test_cancel_ai_chat_generation_route_returns_cancelled_snapshot(
    monkeypatch: Any,
) -> None:
    generation_id = "generation-route-cancel"

    async def fake_current_user() -> User:
        return _user()

    async def fake_redis() -> FakeRedis:
        return FakeRedis()

    async def fake_cancel_service(**kwargs: Any) -> dict[str, Any]:
        assert kwargs["generation_id"] == generation_id
        return {
            "generation_id": generation_id,
            "session_id": str(uuid.uuid4()),
            "prompt": "请停止生成",
            "status": "cancelled",
            "title": "停止测试",
            "reasoning_content": "部分思考",
            "content": "部分回答",
            "error": None,
            "revision": 2,
            "ttl": 120,
        }

    monkeypatch.setattr(
        "app.api.routes.ai_chat.cancel_ai_chat_generation_service",
        fake_cancel_service,
    )
    app.dependency_overrides[get_current_user] = fake_current_user
    app.dependency_overrides[get_redis] = fake_redis
    try:
        client = TestClient(app)
        response = client.post(
            f"/api/v1/ai/chat/generations/{generation_id}/cancel",
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["content"] == "部分回答"


def test_ai_chat_conversation_list_uses_default_page_size(
    monkeypatch: Any,
) -> None:
    captured_params: dict[str, Any] = {}

    async def fake_current_user() -> User:
        return _user()

    def fake_db() -> Session:
        return _session()

    def fake_list_service(**kwargs: Any) -> dict[str, Any]:
        captured_params.update(kwargs)
        return {
            "total": 0,
            "page": kwargs["page"],
            "page_size": kwargs["page_size"],
            "items": [],
        }

    monkeypatch.setattr(
        "app.api.routes.ai_chat.list_ai_chat_conversations_service",
        fake_list_service,
    )
    app.dependency_overrides[get_current_user] = fake_current_user
    app.dependency_overrides[get_db] = fake_db
    try:
        client = TestClient(app)
        response = client.get(
            "/api/v1/ai/chat/conversations",
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["page_size"] == 8
    assert captured_params["page"] == 1
    assert captured_params["page_size"] == 8


def test_ai_chat_history_search_forwards_type_and_default_pagination(
    monkeypatch: Any,
) -> None:
    captured_params: dict[str, Any] = {}

    async def fake_current_user() -> User:
        return _user()

    def fake_db() -> Session:
        return _session()

    def fake_search_service(**kwargs: Any) -> dict[str, Any]:
        captured_params.update(kwargs)
        return {
            "total": 1,
            "page": kwargs["page"],
            "page_size": kwargs["page_size"],
            "items": [
                {
                    "conversation_id": str(uuid.uuid4()),
                    "title": "文档会话",
                    "type": "document",
                    "content": "风险报告.pdf",
                    "time": "2026-07-15T10:00:00Z",
                }
            ],
        }

    monkeypatch.setattr(
        "app.api.routes.ai_chat.search_ai_chat_history_service",
        fake_search_service,
    )
    app.dependency_overrides[get_current_user] = fake_current_user
    app.dependency_overrides[get_db] = fake_db
    try:
        client = TestClient(app)
        response = client.get(
            "/api/v1/ai/chat/conversations/search",
            params={"keyword": "风险", "type": "document"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["items"][0]["type"] == "document"
    assert response.json()["items"][0]["time"] == "2026-07-15T10:00:00Z"
    assert captured_params["keyword"] == "风险"
    assert captured_params["result_type"] == "document"
    assert captured_params["page"] == 1
    assert captured_params["page_size"] == 8
