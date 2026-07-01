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
    delete_ai_chat_conversation_service,
    delete_ai_chat_session_service,
    get_ai_chat_conversation_service,
    get_ai_chat_session_service,
    list_ai_chat_conversations_service,
    stream_ai_chat_service,
    update_ai_chat_conversation_title_service,
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


def test_generated_ai_chat_title_rejects_generic_thinking_title() -> None:
    title = ai_chat_service._normalize_generated_title(
        "Thinking Process",
        "如何设计历史会话？",
    )

    assert title == "如何设计历史会话？"


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

    assert 'event: reasoning\ndata: {"content": "自动分析"}' in events[1]
    assert '"reasoning": "自动分析"' in events[-1]


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
