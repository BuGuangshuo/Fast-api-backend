import asyncio
import io
import uuid
import zipfile
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlmodel import Session, SQLModel, create_engine
from starlette.datastructures import FormData, Headers, UploadFile

from app.core.consts import AIChatMsg, RedisKey
from app.models import User
from app.schemas import AIChatStreamRequest
from app.services import ai_chat_service
from app.services.ai_chat_service import (
    build_ai_chat_stream_request_from_multipart,
    cancel_ai_chat_generation_service,
    delete_ai_chat_conversation_service,
    delete_ai_chat_session_service,
    get_ai_chat_conversation_generation_service,
    get_ai_chat_conversation_service,
    get_ai_chat_generation_service,
    get_ai_chat_session_service,
    list_ai_chat_conversations_service,
    search_ai_chat_history_service,
    start_resumable_ai_chat_service,
    stream_ai_chat_generation_service,
    stream_ai_chat_service,
    update_ai_chat_conversation_title_service,
)
from app.tasks.ai_chat import _stream_until_generation_cancelled


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


class FakeJSONResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    async def aread(self) -> bytes:
        return b"upstream error"

    def json(self) -> dict[str, Any]:
        return self.payload


def _user() -> User:
    return User(username="tester", hashed_password="hashed")


def _db_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


async def _collect_stream(
    redis: FakeRedis,
    user: User,
    request: AIChatStreamRequest,
    session: Session | None = None,
) -> list[str]:
    return [
        event
        async for event in stream_ai_chat_service(
            redis=redis,
            current_user=user,
            request=request,
            session=session,
        )
    ]


def _docx_bytes(text: str) -> bytes:
    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>{text}</w:t></w:r></w:p>
  </w:body>
</w:document>
"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def _xlsx_bytes() -> bytes:
    shared_strings_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <si><t>项目</t></si>
  <si><t>金额</t></si>
  <si><t>GP Plus</t></si>
</sst>
"""
    sheet_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c t="s"><v>0</v></c><c t="s"><v>1</v></c></row>
    <row r="2"><c t="s"><v>2</v></c><c><v>108</v></c></row>
  </sheetData>
</worksheet>
"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", shared_strings_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buffer.getvalue()


def _pptx_bytes(text: str) -> bytes:
    slide_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld>
</p:sld>
"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", slide_xml)
    return buffer.getvalue()


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
    assert captured_payloads[0]["model"] == "Qwen3.5-9B-MLX-4bit"
    assert captured_payloads[0]["stream"] is True
    assert captured_payloads[0]["messages"][-1] == {"role": "user", "content": "你好"}
    assert captured_headers[0]["Authorization"] == "Bearer test-api-key"

    assert len(redis.store) == 1
    history = next(iter(redis.store.values()))
    assert history == [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好"},
    ]


def test_stream_ai_chat_persists_conversation_and_can_continue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_payloads: list[dict[str, Any]] = []
    captured_title_payloads: list[dict[str, Any]] = []

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
            _ = (method, url, headers)
            captured_payloads.append(json)
            answer = "第一轮回答" if len(captured_payloads) == 1 else "第二轮回答"
            return FakeStreamResponse(
                [
                    'data: {"choices":[{"delta":{"reasoning_content":"分析用户想要历史会话接口标题。"}}]}',
                    f'data: {{"choices":[{{"delta":{{"content":"{answer}"}}}}]}}',
                    "data: [DONE]",
                ]
            )

        async def post(
            self,
            url: str,
            json: dict[str, Any],
            headers: dict[str, str],
        ) -> FakeJSONResponse:
            _ = (url, headers)
            captured_title_payloads.append(json)
            return FakeJSONResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "历史会话设计",
                            }
                        }
                    ]
                }
            )

    monkeypatch.setattr(ai_chat_service.httpx, "AsyncClient", FakeAsyncClient)
    session = _db_session()
    redis = FakeRedis()
    user = _user()

    events = asyncio.run(
        _collect_stream(
            redis,
            user,
            AIChatStreamRequest(message="如何设计历史会话？"),
            session=session,
        )
    )
    session_id = events[0].split('"session_id": "')[1].split('"')[0]
    title_event = next(event for event in events if event.startswith("event: title"))
    delta_event = next(event for event in events if event.startswith("event: delta"))
    assert events.index(title_event) < events.index(delta_event)
    assert 'event: title\ndata: {"session_id":' in title_event
    assert '"title": "历史会话设计"' in title_event
    assert captured_title_payloads[0]["stream"] is False
    assert captured_title_payloads[0]["chat_template_kwargs"] == {
        "enable_thinking": False
    }
    title_context = captured_title_payloads[0]["messages"][1]["content"]
    assert title_context == "用户提问：如何设计历史会话？"
    assert "思考摘要" not in title_context
    assert "回答开头" not in title_context

    conversation_id = uuid.UUID(session_id)
    detail = get_ai_chat_conversation_service(
        session=session,
        current_user=user,
        conversation_id=conversation_id,
    )
    assert detail.title == "历史会话设计"
    assert [message.content for message in detail.messages] == [
        "如何设计历史会话？",
        "第一轮回答",
    ]

    asyncio.run(
        _collect_stream(
            redis,
            user,
            AIChatStreamRequest(session_id=session_id, message="继续补充接口"),
            session=session,
        )
    )

    assert captured_payloads[1]["messages"] == [
        {"role": "user", "content": "如何设计历史会话？"},
        {"role": "assistant", "content": "第一轮回答"},
        {"role": "user", "content": "继续补充接口"},
    ]
    conversations = list_ai_chat_conversations_service(
        session=session,
        current_user=user,
        page=1,
        page_size=20,
    )
    assert conversations.total == 1
    assert conversations.items[0].title == "历史会话设计"


def test_stream_ai_chat_saves_partial_reply_when_client_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delta_received = asyncio.Event()

    async def fake_iter_openai_deltas(
        payload: dict[str, Any],
    ) -> AsyncIterator[tuple[str, str]]:
        _ = payload
        yield "delta", "终止前内容"
        await asyncio.Event().wait()

    async def fake_generate_title(*, user_message: str) -> str:
        _ = user_message
        return "手动终止测试"

    monkeypatch.setattr(
        ai_chat_service,
        "_iter_openai_deltas",
        fake_iter_openai_deltas,
    )
    monkeypatch.setattr(
        ai_chat_service,
        "_generate_conversation_title",
        fake_generate_title,
    )
    session = _db_session()
    redis = FakeRedis()
    user = _user()

    async def stop_after_first_delta() -> str:
        events: list[str] = []
        stream = stream_ai_chat_service(
            redis=redis,
            current_user=user,
            request=AIChatStreamRequest(message="请生成一段内容"),
            session=session,
        )

        async def consume_stream() -> None:
            async for event in stream:
                events.append(event)
                if event.startswith("event: delta"):
                    delta_received.set()

        consumer = asyncio.create_task(consume_stream())
        await delta_received.wait()
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer

        assert '"content": "终止前内容"' in events[-1]
        return events[0].split('"session_id": "')[1].split('"')[0]

    session_id = asyncio.run(stop_after_first_delta())
    detail = get_ai_chat_conversation_service(
        session=session,
        current_user=user,
        conversation_id=uuid.UUID(session_id),
    )

    assert [message.content for message in detail.messages] == [
        "请生成一段内容",
        "终止前内容",
    ]
    redis_history = next(iter(redis.store.values()))
    assert redis_history[-1] == {
        "role": "assistant",
        "content": "终止前内容",
    }


def test_generated_ai_chat_title_rejects_generic_thinking_title() -> None:
    title = ai_chat_service._normalize_generated_title(
        "Thinking Process",
        "如何设计历史会话？",
    )

    assert title == "如何设计历史会话？"


def test_search_ai_chat_history_returns_all_types_and_supports_filtering() -> None:
    session = _db_session()
    user = _user()
    other_user = User(username="other-user", hashed_password="hashed")

    ai_chat_service.crud.append_ai_chat_exchange(
        session,
        conversation_id=uuid.uuid4(),
        user_id=user.id,
        title="风险报告分析",
        user_message="请分析风险报告中的异常数据",
        assistant_message="正在分析",
        user_attachments=[
            {
                "filename": "docs/风险报告.pdf",
                "content_type": "application/pdf",
                "size": 1024,
            }
        ],
    )
    ai_chat_service.crud.append_ai_chat_exchange(
        session=session,
        conversation_id=uuid.uuid4(),
        user_id=other_user.id,
        title="其他用户风险报告",
        user_message="风险报告",
        assistant_message="不可见",
        user_attachments=[{"filename": "风险报告.docx", "size": 128}],
    )

    all_results = search_ai_chat_history_service(
        session=session,
        current_user=user,
        keyword=" 风险报告 ",
        result_type=None,
        page=1,
        page_size=8,
    )
    conversation_results = search_ai_chat_history_service(
        session=session,
        current_user=user,
        keyword="风险报告",
        result_type="conversation",
        page=1,
        page_size=8,
    )
    document_results = search_ai_chat_history_service(
        session=session,
        current_user=user,
        keyword="风险报告",
        result_type="document",
        page=1,
        page_size=8,
    )

    assert all_results.total == 2
    assert {item.type for item in all_results.items} == {"conversation", "document"}
    assert all(item.time is not None for item in all_results.items)
    assert conversation_results.total == 1
    assert conversation_results.items[0].type == "conversation"
    assert "风险报告" in conversation_results.items[0].content
    assert document_results.total == 1
    assert document_results.items[0].type == "document"
    assert document_results.items[0].content == "docs/风险报告.pdf"


def test_search_ai_chat_history_paginates_combined_results() -> None:
    session = _db_session()
    user = _user()
    ai_chat_service.crud.append_ai_chat_exchange(
        session,
        conversation_id=uuid.uuid4(),
        user_id=user.id,
        title="接口检索",
        user_message="接口检索正文",
        assistant_message="完成",
        user_attachments=[{"filename": "接口检索说明.md", "size": 64}],
    )

    first_page = search_ai_chat_history_service(
        session=session,
        current_user=user,
        keyword="接口检索",
        result_type=None,
        page=1,
        page_size=1,
    )
    second_page = search_ai_chat_history_service(
        session=session,
        current_user=user,
        keyword="接口检索",
        result_type=None,
        page=2,
        page_size=1,
    )

    assert first_page.total == 2
    assert second_page.total == 2
    assert len(first_page.items) == 1
    assert len(second_page.items) == 1
    assert {first_page.items[0].type, second_page.items[0].type} == {
        "conversation",
        "document",
    }


def test_update_and_delete_ai_chat_conversation() -> None:
    session = _db_session()
    user = _user()
    conversation_id = uuid.uuid4()
    ai_chat_service.crud.append_ai_chat_exchange(
        session,
        conversation_id=conversation_id,
        user_id=user.id,
        title="旧标题",
        user_message="hello",
        assistant_message="world",
    )

    updated = update_ai_chat_conversation_title_service(
        session=session,
        current_user=user,
        conversation_id=conversation_id,
        title=" 新标题 ",
    )
    assert updated.title == "新标题"

    message = delete_ai_chat_conversation_service(
        session=session,
        current_user=user,
        conversation_id=conversation_id,
    )
    assert message.message == AIChatMsg.SESSION_DELETED
    conversations = list_ai_chat_conversations_service(
        session=session,
        current_user=user,
        page=1,
        page_size=20,
    )
    assert conversations.total == 0


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


def test_stream_ai_chat_includes_text_attachment_context(
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
                    'data: {"choices":[{"delta":{"content":"收到"}}]}',
                    "data: [DONE]",
                ]
            )

    monkeypatch.setattr(ai_chat_service.httpx, "AsyncClient", FakeAsyncClient)

    asyncio.run(
        _collect_stream(
            FakeRedis(),
            _user(),
            AIChatStreamRequest(
                message="总结附件",
                attachments=[
                    {
                        "filename": "docs/readme.md",
                        "content_type": "text/markdown",
                        "size": 11,
                        "text": "# 标题\n内容",
                    }
                ],
            ),
        )
    )

    user_message = captured_payloads[0]["messages"][-1]["content"]
    assert isinstance(user_message, str)
    assert "docs/readme.md" in user_message
    assert "# 标题\n内容" in user_message


def test_stream_ai_chat_persists_attachment_metadata_for_history(
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
            _ = (method, url, json, headers)
            return FakeStreamResponse(
                [
                    'data: {"choices":[{"delta":{"content":"收到"}}]}',
                    "data: [DONE]",
                ]
            )

        async def post(
            self,
            url: str,
            json: dict[str, Any],
            headers: dict[str, str],
        ) -> FakeJSONResponse:
            _ = (url, json, headers)
            return FakeJSONResponse({"choices": [{"message": {"content": "附件对话"}}]})

    monkeypatch.setattr(ai_chat_service.httpx, "AsyncClient", FakeAsyncClient)
    session = _db_session()
    redis = FakeRedis()
    user = _user()

    events = asyncio.run(
        _collect_stream(
            redis,
            user,
            AIChatStreamRequest(
                message="总结附件",
                attachments=[
                    {
                        "filename": "docs/readme.md",
                        "content_type": "text/markdown",
                        "size": 11,
                        "text": "# 标题\n内容",
                    }
                ],
            ),
            session=session,
        )
    )
    session_id = events[0].split('"session_id": "')[1].split('"')[0]

    detail = get_ai_chat_conversation_service(
        session=session,
        current_user=user,
        conversation_id=uuid.UUID(session_id),
    )
    assert detail.messages[0].attachments[0].model_dump() == {
        "filename": "docs/readme.md",
        "content_type": "text/markdown",
        "size": 11,
    }

    session_detail = asyncio.run(
        get_ai_chat_session_service(
            session=session,
            redis=redis,
            current_user=user,
            session_id=session_id,
        )
    )
    assert session_detail.messages[0].attachments[0].filename == "docs/readme.md"


def test_stream_ai_chat_includes_image_attachment_part(
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
                    'data: {"choices":[{"delta":{"content":"看到了"}}]}',
                    "data: [DONE]",
                ]
            )

    monkeypatch.setattr(ai_chat_service.httpx, "AsyncClient", FakeAsyncClient)

    asyncio.run(
        _collect_stream(
            FakeRedis(),
            _user(),
            AIChatStreamRequest(
                message="看图",
                attachments=[
                    {
                        "filename": "image.png",
                        "content_type": "image/png",
                        "size": 8,
                        "image_data_url": "data:image/png;base64,aW1hZ2U=",
                    }
                ],
            ),
        )
    )

    user_content = captured_payloads[0]["messages"][-1]["content"]
    assert isinstance(user_content, list)
    assert user_content[0]["type"] == "text"
    assert user_content[1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,aW1hZ2U="},
    }


def test_build_ai_chat_stream_request_from_multipart_reads_folder_files() -> None:
    form = FormData(
        [
            ("message", "分析这些文件"),
            ("relative_paths", '["folder/a.txt", "folder/b.png"]'),
            (
                "files",
                UploadFile(
                    filename="a.txt",
                    file=io.BytesIO(b"hello"),
                    headers=Headers({"content-type": "text/plain"}),
                ),
            ),
            (
                "files",
                UploadFile(
                    filename="b.png",
                    file=io.BytesIO(b"image"),
                    headers=Headers({"content-type": "image/png"}),
                ),
            ),
        ]
    )

    request = asyncio.run(build_ai_chat_stream_request_from_multipart(form))

    assert request.message == "分析这些文件"
    assert [attachment.filename for attachment in request.attachments] == [
        "folder/a.txt",
        "folder/b.png",
    ]
    assert request.attachments[0].text == "hello"
    assert request.attachments[1].image_data_url == "data:image/png;base64,aW1hZ2U="


def test_build_ai_chat_stream_request_from_multipart_extracts_docx_text() -> None:
    form = FormData(
        [
            ("message", "总结报销说明"),
            (
                "files",
                UploadFile(
                    filename="GP Plus 会员报销说明.docx",
                    file=io.BytesIO(_docx_bytes("报销范围包括 GP Plus 会员费用。")),
                    headers=Headers(
                        {
                            "content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                        }
                    ),
                ),
            ),
        ]
    )

    request = asyncio.run(build_ai_chat_stream_request_from_multipart(form))

    assert request.attachments[0].filename == "GP Plus 会员报销说明.docx"
    assert request.attachments[0].text == "报销范围包括 GP Plus 会员费用。"


def test_build_ai_chat_stream_request_from_multipart_extracts_xlsx_text() -> None:
    form = FormData(
        [
            ("message", "总结表格"),
            (
                "files",
                UploadFile(
                    filename="报销明细.xlsx",
                    file=io.BytesIO(_xlsx_bytes()),
                    headers=Headers(
                        {
                            "content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        }
                    ),
                ),
            ),
        ]
    )

    request = asyncio.run(build_ai_chat_stream_request_from_multipart(form))

    assert "项目\t金额" in (request.attachments[0].text or "")
    assert "GP Plus\t108" in (request.attachments[0].text or "")


def test_build_ai_chat_stream_request_from_multipart_extracts_pptx_text() -> None:
    form = FormData(
        [
            ("message", "总结演示文稿"),
            (
                "files",
                UploadFile(
                    filename="报销说明.pptx",
                    file=io.BytesIO(_pptx_bytes("报销流程分为申请、审批、打款。")),
                    headers=Headers(
                        {
                            "content-type": "application/vnd.openxmlformats-officedocument.presentationml.presentation"
                        }
                    ),
                ),
            ),
        ]
    )

    request = asyncio.run(build_ai_chat_stream_request_from_multipart(form))

    assert "报销流程分为申请、审批、打款。" in (request.attachments[0].text or "")


def test_build_ai_chat_stream_request_from_multipart_decodes_unknown_text_file() -> (
    None
):
    form = FormData(
        [
            ("message", "解释代码"),
            (
                "files",
                UploadFile(
                    filename="Dockerfile",
                    file=io.BytesIO(b"FROM python:3.14\nRUN pytest\n"),
                    headers=Headers({"content-type": "application/octet-stream"}),
                ),
            ),
        ]
    )

    request = asyncio.run(build_ai_chat_stream_request_from_multipart(form))

    assert request.attachments[0].text == "FROM python:3.14\nRUN pytest\n"


def test_build_ai_chat_stream_request_from_multipart_extracts_pdf_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePage:
        def extract_text(self) -> str:
            return "PDF 报销说明正文"

    class FakeReader:
        def __init__(self, source: io.BytesIO) -> None:
            _ = source
            self.pages = [FakePage()]

    class FakePypdf:
        PdfReader = FakeReader

    def fake_import_module(name: str) -> object:
        assert name == "pypdf"
        return FakePypdf

    monkeypatch.setattr(ai_chat_service.importlib, "import_module", fake_import_module)
    form = FormData(
        [
            ("message", "总结 PDF"),
            (
                "files",
                UploadFile(
                    filename="报销说明.pdf",
                    file=io.BytesIO(b"%PDF-1.7"),
                    headers=Headers({"content-type": "application/pdf"}),
                ),
            ),
        ]
    )

    request = asyncio.run(build_ai_chat_stream_request_from_multipart(form))

    assert request.attachments[0].text == "PDF 报销说明正文"


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


def test_stream_ai_chat_forwards_dropdown_thinking_mode(
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
            AIChatStreamRequest(message="hello", thinking_mode="thinking"),
        )
    )
    asyncio.run(
        _collect_stream(
            FakeRedis(),
            _user(),
            AIChatStreamRequest(message="hello", thinking_mode="fast"),
        )
    )
    asyncio.run(
        _collect_stream(
            FakeRedis(),
            _user(),
            AIChatStreamRequest(message="hello", thinking_mode="auto"),
        )
    )

    assert captured_payloads[0]["chat_template_kwargs"] == {"enable_thinking": True}
    assert captured_payloads[1]["chat_template_kwargs"] == {"enable_thinking": False}
    assert "chat_template_kwargs" not in captured_payloads[2]


def test_build_ai_chat_stream_request_from_multipart_reads_thinking_mode() -> None:
    form = FormData([("message", "hello"), ("thinking_mode", "fast")])

    request = asyncio.run(build_ai_chat_stream_request_from_multipart(form))

    assert request.thinking_mode == "fast"
    assert request.resolved_enable_thinking is False


def test_stream_ai_chat_auto_mode_emits_reasoning_when_upstream_returns_it(
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
                    'data: {"choices":[{"delta":{"reasoning_content":"自动分析"}}]}',
                    'data: {"choices":[{"delta":{"content":"答案"}}]}',
                    "data: [DONE]",
                ]
            )

    monkeypatch.setattr(ai_chat_service.httpx, "AsyncClient", FakeAsyncClient)

    events = asyncio.run(
        _collect_stream(
            FakeRedis(),
            _user(),
            AIChatStreamRequest(message="hello", thinking_mode="auto"),
        )
    )

    assert (
        'event: reasoning\ndata: {"content": "自动分析", '
        '"reasoning_title": null, "reasoning_content": "自动分析"}'
    ) in events[1]
    assert '"reasoning": "自动分析"' in events[-1]
    assert '"reasoning_title": null' in events[-1]
    assert '"reasoning_content": "自动分析"' in events[-1]


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

    assert (
        'event: reasoning\ndata: {"content": "先分析", '
        '"reasoning_title": null, "reasoning_content": "先分析"}'
    ) in events[1]
    assert 'event: delta\ndata: {"content": "答案"}' in events[2]
    assert '"reasoning": "先分析"' in events[-1]
    assert '"reasoning_title": null' in events[-1]
    assert '"reasoning_content": "先分析"' in events[-1]

    history = next(iter(redis.store.values()))
    assert history == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "答案"},
    ]


def test_stream_ai_chat_splits_reasoning_title_and_content(
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
            _ = (method, url, json, headers)
            return FakeStreamResponse(
                [
                    'data: {"choices":[{"delta":{"reasoning_content":"# 思考摘要\\n"}}]}',
                    'data: {"choices":[{"delta":{"reasoning_content":"先判断问题，再组织回答"}}]}',
                    'data: {"choices":[{"delta":{"content":"答案"}}]}',
                    "data: [DONE]",
                ]
            )

        async def post(
            self,
            url: str,
            json: dict[str, Any],
            headers: dict[str, str],
        ) -> FakeJSONResponse:
            _ = (url, json, headers)
            return FakeJSONResponse({"choices": [{"message": {"content": "思考拆分"}}]})

    monkeypatch.setattr(ai_chat_service.httpx, "AsyncClient", FakeAsyncClient)
    session = _db_session()
    user = _user()

    events = asyncio.run(
        _collect_stream(
            FakeRedis(),
            user,
            AIChatStreamRequest(message="hello", enable_thinking=True),
            session=session,
        )
    )
    session_id = events[0].split('"session_id": "')[1].split('"')[0]
    reasoning_events = [
        event for event in events if event.startswith("event: reasoning")
    ]

    assert '"reasoning_title": "思考摘要"' in reasoning_events[0]
    assert '"reasoning_content": ""' in reasoning_events[0]
    assert '"reasoning_title": "思考摘要"' in reasoning_events[1]
    assert '"reasoning_content": "先判断问题，再组织回答"' in reasoning_events[1]
    assert '"reasoning": "# 思考摘要\\n先判断问题，再组织回答"' in events[-1]
    assert '"reasoning_title": "思考摘要"' in events[-1]
    assert '"reasoning_content": "先判断问题，再组织回答"' in events[-1]

    detail = get_ai_chat_conversation_service(
        session=session,
        current_user=user,
        conversation_id=uuid.UUID(session_id),
    )
    assert detail.messages[1].reasoning_title == "思考摘要"
    assert detail.messages[1].reasoning_content == "先判断问题，再组织回答"


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


def test_stream_ai_chat_falls_back_when_thinking_only_returns_duplicated_content(
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
            _ = (method, url, headers)
            captured_payloads.append(json)
            if len(captured_payloads) == 1:
                return FakeStreamResponse(
                    [
                        'data: {"choices":[{"delta":{"reasoning_content":"先分析","content":"先分析"}}]}',
                        'data: {"choices":[{"delta":{},"finish_reason":"length"}]}',
                        "data: [DONE]",
                    ]
                )
            return FakeStreamResponse(
                [
                    'data: {"choices":[{"delta":{"content":"正式回答"}}]}',
                    'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
                    "data: [DONE]",
                ]
            )

        async def post(
            self,
            url: str,
            json: dict[str, Any],
            headers: dict[str, str],
        ) -> FakeJSONResponse:
            _ = (url, json, headers)
            return FakeJSONResponse({"choices": [{"message": {"content": "附件分析"}}]})

    monkeypatch.setattr(ai_chat_service.httpx, "AsyncClient", FakeAsyncClient)
    session = _db_session()
    user = _user()

    events = asyncio.run(
        _collect_stream(
            FakeRedis(),
            user,
            AIChatStreamRequest(
                message="分析附件",
                thinking_mode="thinking",
                attachments=[
                    {
                        "filename": "report.txt",
                        "content_type": "text/plain",
                        "size": 4,
                        "text": "内容",
                    }
                ],
            ),
            session=session,
        )
    )
    session_id = events[0].split('"session_id": "')[1].split('"')[0]

    assert len(captured_payloads) == 2
    assert captured_payloads[0]["chat_template_kwargs"] == {"enable_thinking": True}
    assert captured_payloads[1]["chat_template_kwargs"] == {"enable_thinking": False}
    assert 'event: title\ndata: {"session_id":' in events[1]
    assert '"title": "附件分析"' in events[1]
    assert any(
        event == 'event: delta\ndata: {"content": "正式回答"}\n\n' for event in events
    )
    assert '"message": "正式回答"' in events[-1]
    assert '"reasoning": "先分析"' in events[-1]

    detail = get_ai_chat_conversation_service(
        session=session,
        current_user=user,
        conversation_id=uuid.UUID(session_id),
    )
    assert detail.title == "附件分析"
    assert detail.messages[1].content == "正式回答"
    assert detail.messages[1].reasoning_content == "先分析"


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


def test_start_resumable_ai_chat_creates_visible_conversation_and_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queued_args: list[tuple[str, str]] = []

    def fake_delay(generation_id: str, user_id: str) -> None:
        queued_args.append((generation_id, user_id))

    monkeypatch.setattr(
        "app.tasks.ai_chat.generate_ai_chat_response_task.delay",
        fake_delay,
    )
    session = _db_session()
    redis = FakeRedis()
    user = _user()

    async def start_and_stop() -> tuple[str, str]:
        stream = start_resumable_ai_chat_service(
            session=session,
            redis=redis,
            current_user=user,
            request=AIChatStreamRequest(message="刷新后继续", resumable=True),
        )
        generation_event = await anext(stream)
        status_event = await anext(stream)
        await stream.aclose()
        return generation_event, status_event

    generation_event, status_event = asyncio.run(start_and_stop())
    generation_id = generation_event.split('"generation_id": "')[1].split('"')[0]
    session_id = generation_event.split('"session_id": "')[1].split('"')[0]

    assert generation_event.startswith("event: generation")
    assert '"status": "queued"' in status_event
    assert queued_args == [(generation_id, str(user.id))]
    assert RedisKey.ai_chat_generation(str(user.id), generation_id) in redis.store
    assert (
        RedisKey.ai_chat_generation_request(str(user.id), generation_id) in redis.store
    )
    assert (
        redis.store[RedisKey.ai_chat_conversation_generation(str(user.id), session_id)]
        == generation_id
    )

    conversations = list_ai_chat_conversations_service(
        session=session,
        current_user=user,
        page=1,
        page_size=8,
    )
    assert conversations.total == 1
    assert str(conversations.items[0].id) == session_id
    detail = get_ai_chat_conversation_service(
        session=session,
        current_user=user,
        conversation_id=uuid.UUID(session_id),
    )
    assert [(message.role, message.content) for message in detail.messages] == [
        ("user", "刷新后继续")
    ]
    snapshot = asyncio.run(
        get_ai_chat_conversation_generation_service(
            session=session,
            redis=redis,
            current_user=user,
            conversation_id=uuid.UUID(session_id),
        )
    )
    assert snapshot.generation_id == generation_id
    assert snapshot.prompt == "刷新后继续"
    assert snapshot.status == "queued"


def test_resumable_worker_does_not_duplicate_persisted_user_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_payloads: list[dict[str, Any]] = []

    async def fake_iter_openai_deltas(
        payload: dict[str, Any],
    ) -> AsyncIterator[tuple[str, str]]:
        captured_payloads.append(payload)
        yield "delta", "后台回答"

    async def fake_generate_title(*, user_message: str) -> str:
        _ = user_message
        return "后台恢复测试"

    monkeypatch.setattr(
        ai_chat_service,
        "_iter_openai_deltas",
        fake_iter_openai_deltas,
    )
    monkeypatch.setattr(
        ai_chat_service,
        "_generate_conversation_title",
        fake_generate_title,
    )
    session = _db_session()
    redis = FakeRedis()
    user = _user()
    conversation = ai_chat_service.crud.create_ai_chat_conversation(
        session,
        conversation_id=uuid.uuid4(),
        user_id=user.id,
        title="新聊天",
    )
    ai_chat_service.crud.append_ai_chat_user_message(
        session,
        conversation=conversation,
        content="已经落库的问题",
    )

    events = asyncio.run(
        _collect_stream_with_persisted_user(
            redis=redis,
            user=user,
            request=AIChatStreamRequest(
                session_id=str(conversation.id),
                message="已经落库的问题",
            ),
            session=session,
        )
    )
    detail = get_ai_chat_conversation_service(
        session=session,
        current_user=user,
        conversation_id=conversation.id,
    )

    assert captured_payloads[0]["messages"] == [
        {"role": "user", "content": "已经落库的问题"}
    ]
    assert events[-1].startswith("event: done")
    assert [(message.role, message.content) for message in detail.messages] == [
        ("user", "已经落库的问题"),
        ("assistant", "后台回答"),
    ]


async def _collect_stream_with_persisted_user(
    *,
    redis: FakeRedis,
    user: User,
    request: AIChatStreamRequest,
    session: Session,
) -> list[str]:
    return [
        event
        async for event in stream_ai_chat_service(
            redis=redis,
            current_user=user,
            request=request,
            session=session,
            user_message_persisted=True,
        )
    ]


def test_generation_snapshot_can_resume_from_offsets() -> None:
    redis = FakeRedis()
    user = _user()
    generation_id = "generation-test"
    key = RedisKey.ai_chat_generation(str(user.id), generation_id)
    redis.store[key] = {
        "generation_id": generation_id,
        "session_id": str(uuid.uuid4()),
        "prompt": "请继续生成",
        "status": "completed",
        "title": "恢复回答",
        "reasoning_content": "思考过程",
        "content": "最终回答",
        "error": None,
        "revision": 4,
    }
    redis.ttls[key] = 120

    snapshot = asyncio.run(
        get_ai_chat_generation_service(
            redis=redis,
            current_user=user,
            generation_id=generation_id,
        )
    )
    assert snapshot.status == "completed"
    assert snapshot.prompt == "请继续生成"
    assert snapshot.reasoning_content == "思考过程"
    assert snapshot.content == "最终回答"
    assert snapshot.ttl == 120

    events = asyncio.run(
        _collect_generation_stream(
            redis=redis,
            user=user,
            generation_id=generation_id,
            reasoning_offset=2,
            content_offset=2,
        )
    )
    assert any('"content": "过程"' in event for event in events)
    assert any('"content": "回答"' in event for event in events)
    assert events[-1].startswith("event: done")


def test_cancel_generation_is_idempotent_and_stops_future_streams() -> None:
    redis = FakeRedis()
    user = _user()
    generation_id = "generation-cancel"
    key = RedisKey.ai_chat_generation(str(user.id), generation_id)
    redis.store[key] = {
        "generation_id": generation_id,
        "session_id": str(uuid.uuid4()),
        "prompt": "请停止生成",
        "status": "answering",
        "title": "停止测试",
        "reasoning_content": "部分思考",
        "content": "部分回答",
        "error": None,
        "revision": 3,
    }
    redis.ttls[key] = 120

    first_snapshot = asyncio.run(
        cancel_ai_chat_generation_service(
            redis=redis,
            current_user=user,
            generation_id=generation_id,
        )
    )
    second_snapshot = asyncio.run(
        cancel_ai_chat_generation_service(
            redis=redis,
            current_user=user,
            generation_id=generation_id,
        )
    )

    assert first_snapshot.status == "cancelled"
    assert first_snapshot.prompt == "请停止生成"
    assert first_snapshot.content == "部分回答"
    assert first_snapshot.reasoning_content == "部分思考"
    assert first_snapshot.revision == 4
    assert second_snapshot.status == "cancelled"
    assert second_snapshot.revision == 4
    assert (
        redis.store[RedisKey.ai_chat_generation_cancelled(str(user.id), generation_id)]
        is True
    )

    events = asyncio.run(
        _collect_generation_stream(
            redis=redis,
            user=user,
            generation_id=generation_id,
            reasoning_offset=len(first_snapshot.reasoning_content),
            content_offset=len(first_snapshot.content),
        )
    )
    assert len(events) == 2
    assert events[0].startswith("event: status")
    assert '"status": "cancelled"' in events[0]
    assert events[1].startswith("event: title")


def test_worker_closes_upstream_stream_after_generation_is_cancelled() -> None:
    redis = FakeRedis()
    cancelled_key = "generation-cancelled-test"
    upstream_closed = False

    async def blocking_stream() -> AsyncIterator[str]:
        nonlocal upstream_closed
        try:
            yield "event: delta\ndata: {}\n\n"
            await asyncio.Event().wait()
        finally:
            upstream_closed = True

    async def consume_until_cancelled() -> None:
        stream = _stream_until_generation_cancelled(
            stream=blocking_stream(),
            redis=redis,
            cancelled_key=cancelled_key,
        )
        assert await anext(stream) == "event: delta\ndata: {}\n\n"
        await redis.set(cancelled_key, True, 120)
        with pytest.raises(StopAsyncIteration):
            await anext(stream)

    asyncio.run(consume_until_cancelled())

    assert upstream_closed is True


async def _collect_generation_stream(
    *,
    redis: FakeRedis,
    user: User,
    generation_id: str,
    reasoning_offset: int,
    content_offset: int,
) -> list[str]:
    return [
        event
        async for event in stream_ai_chat_generation_service(
            redis=redis,
            current_user=user,
            generation_id=generation_id,
            reasoning_offset=reasoning_offset,
            content_offset=content_offset,
        )
    ]
