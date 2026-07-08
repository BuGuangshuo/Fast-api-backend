"""AI 对话 Service。"""

import base64
import importlib
import io
import json
import mimetypes
import re
import uuid
import zipfile
from collections.abc import AsyncIterator
from pathlib import PurePosixPath
from typing import Any, Literal, cast
from xml.etree import ElementTree

import httpx
from fastapi import HTTPException, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlmodel import Session
from starlette.datastructures import FormData, UploadFile

from app import crud
from app.core.config import settings
from app.core.consts import AIChatMsg, RedisKey
from app.core.redis import RedisService
from app.models import User
from app.schemas import (
    AIChatAttachment,
    AIChatAttachmentPublic,
    AIChatConversationListItem,
    AIChatConversationMessagePublic,
    AIChatConversationResponse,
    AIChatMessage,
    AIChatSessionResponse,
    AIChatStreamRequest,
    Message,
    PaginatedResponse,
)
from app.utils import get_logger

logger = get_logger(__name__)

_MULTIPART_LIST_FIELDS = {"files", "file", "attachments", "attachment", "images"}
_RELATIVE_PATH_FIELDS = {"relative_paths", "relativePaths", "paths", "file_paths"}
_TEXT_MIME_TYPES = {
    "application/csv",
    "application/json",
    "application/ld+json",
    "application/sql",
    "application/toml",
    "application/xml",
    "application/x-ndjson",
    "application/x-yaml",
    "application/yaml",
    "application/javascript",
    "application/typescript",
    "application/x-httpd-php",
    "application/x-sh",
}
_TEXT_SUFFIXES = {
    ".bash",
    ".bat",
    ".c",
    ".cfg",
    ".conf",
    ".cpp",
    ".csv",
    ".css",
    ".dockerfile",
    ".env",
    ".go",
    ".h",
    ".hpp",
    ".htm",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".jsx",
    ".json",
    ".jsonl",
    ".kt",
    ".log",
    ".md",
    ".php",
    ".properties",
    ".py",
    ".rb",
    ".rs",
    ".scss",
    ".sh",
    ".sql",
    ".swift",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".vue",
    ".xml",
    ".yaml",
    ".yml",
    ".zsh",
}
_TEXT_FILENAMES = {
    "dockerfile",
    "makefile",
    "gemfile",
    "rakefile",
    "requirements",
}
_DOCX_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
_XLSX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_PPTX_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)
_PDF_MIME_TYPE = "application/pdf"
_DOCX_EXTRA_PREFIXES = (
    "word/header",
    "word/footer",
    "word/footnotes",
    "word/endnotes",
)
_PPTX_TEXT_PREFIXES = (
    "ppt/slides/slide",
    "ppt/notesSlides/notesSlide",
)
_TITLE_MAX_LENGTH = 30
_TITLE_CONTEXT_MAX_LENGTH = 2000
_TITLE_SYSTEM_PROMPT = (
    "你是对话标题生成器。只根据用户提问总结一个简短标题。"
    "标题必须概括用户真正想问的内容，不要使用 Thinking Process、思考过程、标题等泛化词。"
    "只输出标题本身，不要解释，不要加引号，不要超过15个汉字或30个英文字符。"
)
_GENERIC_TITLE_VALUES = {
    "thinking process",
    "thinking",
    "思考过程",
    "思考流程",
    "思考",
    "分析过程",
    "title",
    "标题",
    "对话标题",
}
_PERSISTENT_MESSAGE_ROLES = {"user", "assistant"}
_REASONING_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(?P<title>.+?)\s*#*\s*$")
_REASONING_LABEL_RE = re.compile(
    r"^\s*(?:思考标题|标题|title)\s*[:：]\s*(?P<title>.+?)\s*$",
    flags=re.IGNORECASE,
)
_REASONING_BOLD_RE = re.compile(r"^\s*\*\*(?P<title>[^*]+?)\*\*\s*$")


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


def _parse_conversation_id(session_id: str | None) -> uuid.UUID | None:
    if session_id is None:
        return None
    try:
        return uuid.UUID(session_id)
    except ValueError:
        return None


def _sse_event(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def _normalize_reasoning_title(title: str) -> str:
    """清理模型思考标题周围的 Markdown / 引号噪声。"""
    return re.sub(r"\s+", " ", title).strip(" \t#*`\"'“”《》【】[]()（）")


def _split_reasoning_title_and_content(
    reasoning_content: str | None,
) -> tuple[str | None, str | None]:
    """将模型 reasoning 中的首行标题拆给前端展示。

    数据库存量仍保存原始 reasoning；这里仅在出接口时识别常见的 Markdown 标题、
    “标题：...” 和加粗标题，避免前端重复解析模型格式。
    """
    if reasoning_content is None:
        return None, None

    text = reasoning_content.strip()
    if not text:
        return None, None

    lines = text.splitlines()
    first_line_index = next(
        (index for index, line in enumerate(lines) if line.strip()),
        None,
    )
    if first_line_index is None:
        return None, None

    first_line = lines[first_line_index].strip()
    title = None
    for pattern in (_REASONING_HEADING_RE, _REASONING_LABEL_RE, _REASONING_BOLD_RE):
        match = pattern.match(first_line)
        if match is not None:
            title = _normalize_reasoning_title(match.group("title"))
            break

    if not title:
        return None, text

    body = "\n".join(lines[first_line_index + 1 :]).strip()
    return title, body


def _reasoning_payload_fields(reasoning_content: str | None) -> dict[str, str | None]:
    """生成前端可直接使用的 reasoning 标题和正文。"""
    reasoning_title, parsed_content = _split_reasoning_title_and_content(
        reasoning_content
    )
    return {
        "reasoning_title": reasoning_title,
        "reasoning_content": parsed_content,
    }


def _attachment_public_metadata(
    attachments: list[AIChatAttachment],
) -> list[AIChatAttachmentPublic]:
    """保留历史展示需要的附件元数据，不保存正文或图片 data URL。"""
    return [
        AIChatAttachmentPublic(
            filename=attachment.filename,
            content_type=attachment.content_type,
            size=attachment.size,
        )
        for attachment in attachments
    ]


def _coerce_attachment_metadata(value: Any) -> list[AIChatAttachmentPublic]:
    """兼容旧数据或异常 JSON，只返回前端可展示的附件元数据。"""
    if not isinstance(value, list):
        return []

    attachments: list[AIChatAttachmentPublic] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            attachments.append(AIChatAttachmentPublic.model_validate(item))
        except ValidationError:
            logger.warning("忽略异常 AI 对话附件元数据: %s", item)
    return attachments


def _history_message_dump(message: AIChatMessage) -> dict[str, Any]:
    """缓存历史时保留非空附件，避免旧格式里出现大量空列表。"""
    data = message.model_dump()
    if not message.attachments:
        data.pop("attachments", None)
    return data


def _safe_display_name(filename: str | None) -> str:
    if not filename:
        return "unnamed"
    normalized = filename.replace("\\", "/").lstrip("/")
    parts = [
        part for part in PurePosixPath(normalized).parts if part not in {"", ".", ".."}
    ]
    return "/".join(parts) or "unnamed"


def _first_form_value(form: FormData, field_name: str) -> str | None:
    value = form.get(field_name)
    return value if isinstance(value, str) else None


def _bool_form_value(value: str | None) -> bool | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(value)


def _int_form_value(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    return int(value)


def _float_form_value(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    return float(value)


def _multipart_files(form: FormData) -> list[UploadFile]:
    files: list[UploadFile] = []
    for field_name, value in form.multi_items():
        if isinstance(value, UploadFile) and (
            field_name in _MULTIPART_LIST_FIELDS or value.filename
        ):
            files.append(value)
    return files


def _multipart_relative_paths(form: FormData) -> list[str]:
    paths: list[str] = []
    for field_name, value in form.multi_items():
        if field_name in _RELATIVE_PATH_FIELDS and isinstance(value, str):
            if value.strip().startswith("["):
                try:
                    decoded = json.loads(value)
                except json.JSONDecodeError:
                    paths.append(value)
                    continue
                if isinstance(decoded, list):
                    paths.extend(item for item in decoded if isinstance(item, str))
                    continue
            paths.append(value)
    return paths


def _is_image_upload(filename: str, content_type: str | None) -> bool:
    guessed_type = mimetypes.guess_type(filename)[0]
    return (content_type or guessed_type or "").lower().startswith("image/")


def _is_text_upload(filename: str, content_type: str | None) -> bool:
    media_type = (content_type or mimetypes.guess_type(filename)[0] or "").lower()
    path = PurePosixPath(filename)
    suffix = path.suffix.lower()
    basename = path.name.lower()
    return (
        media_type.startswith("text/")
        or media_type in _TEXT_MIME_TYPES
        or suffix in _TEXT_SUFFIXES
        or basename in _TEXT_FILENAMES
    )


def _is_docx_upload(filename: str, content_type: str | None) -> bool:
    media_type = (content_type or mimetypes.guess_type(filename)[0] or "").lower()
    suffix = PurePosixPath(filename).suffix.lower()
    return suffix == ".docx" or media_type == _DOCX_MIME_TYPE


def _is_xlsx_upload(filename: str, content_type: str | None) -> bool:
    media_type = (content_type or mimetypes.guess_type(filename)[0] or "").lower()
    suffix = PurePosixPath(filename).suffix.lower()
    return suffix == ".xlsx" or media_type == _XLSX_MIME_TYPE


def _is_pptx_upload(filename: str, content_type: str | None) -> bool:
    media_type = (content_type or mimetypes.guess_type(filename)[0] or "").lower()
    suffix = PurePosixPath(filename).suffix.lower()
    return suffix == ".pptx" or media_type == _PPTX_MIME_TYPE


def _is_pdf_upload(filename: str, content_type: str | None) -> bool:
    media_type = (content_type or mimetypes.guess_type(filename)[0] or "").lower()
    suffix = PurePosixPath(filename).suffix.lower()
    return suffix == ".pdf" or media_type == _PDF_MIME_TYPE


def _decode_text_upload(content: bytes) -> str | None:
    if content and content.count(b"\x00") / len(content) > 0.05:
        return None

    for encoding in ("utf-8-sig", "utf-8", "gb18030", "utf-16"):
        try:
            decoded = content.decode(encoding)
        except UnicodeDecodeError:
            continue
        if (
            decoded
            and len(re.findall(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", decoded)) / len(decoded)
            > 0.05
        ):
            return None
        return decoded
    return None


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _extract_word_xml_text(xml_content: bytes) -> str | None:
    """从 WordprocessingML 段落中提取文本，保留基本换行和制表符。"""
    try:
        root = ElementTree.fromstring(xml_content)
    except ElementTree.ParseError:
        return None

    paragraphs: list[str] = []
    for paragraph in root.iter():
        if _xml_local_name(paragraph.tag) != "p":
            continue

        fragments: list[str] = []
        for node in paragraph.iter():
            local_name = _xml_local_name(node.tag)
            if local_name == "t" and node.text:
                fragments.append(node.text)
            elif local_name == "tab":
                fragments.append("\t")
            elif local_name in {"br", "cr"}:
                fragments.append("\n")

        paragraph_text = "".join(fragments).strip()
        if paragraph_text:
            paragraphs.append(paragraph_text)

    text = "\n".join(paragraphs).strip()
    return text or None


def _docx_text_members(names: list[str]) -> list[str]:
    members: list[str] = []
    if "word/document.xml" in names:
        members.append("word/document.xml")
    members.extend(
        sorted(
            name
            for name in names
            if name.endswith(".xml")
            and any(name.startswith(prefix) for prefix in _DOCX_EXTRA_PREFIXES)
        )
    )
    return members


def _extract_docx_text(content: bytes) -> str | None:
    """读取 docx 内部 XML 文本，失败时降级为不可读二进制附件。"""
    if not content:
        return ""

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            sections: list[str] = []
            for member_name in _docx_text_members(archive.namelist()):
                with archive.open(member_name) as member:
                    member_text = _extract_word_xml_text(member.read())
                if member_text:
                    sections.append(member_text)
    except (OSError, RuntimeError, zipfile.BadZipFile):
        logger.warning("无法解析 AI 对话 docx 附件")
        return None

    text = "\n\n".join(sections).strip()
    if not text:
        return None
    return text[: settings.LLM_CHAT_MAX_TEXT_FILE_BYTES]


def _extract_plain_xml_text(xml_content: bytes) -> str | None:
    """从通用 OOXML XML 中提取文本节点。"""
    try:
        root = ElementTree.fromstring(xml_content)
    except ElementTree.ParseError:
        return None

    fragments: list[str] = []
    for node in root.iter():
        if _xml_local_name(node.tag) == "t" and node.text:
            fragments.append(node.text)

    text = " ".join(fragment.strip() for fragment in fragments if fragment.strip())
    return text or None


def _extract_xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        with archive.open("xl/sharedStrings.xml") as member:
            root = ElementTree.fromstring(member.read())
    except (KeyError, ElementTree.ParseError):
        return []

    shared_strings: list[str] = []
    for item in root.iter():
        if _xml_local_name(item.tag) != "si":
            continue
        fragments = [
            node.text
            for node in item.iter()
            if _xml_local_name(node.tag) == "t" and node.text
        ]
        shared_strings.append("".join(fragments))
    return shared_strings


def _extract_xlsx_sheet_text(
    xml_content: bytes, shared_strings: list[str], sheet_name: str
) -> str | None:
    try:
        root = ElementTree.fromstring(xml_content)
    except ElementTree.ParseError:
        return None

    rows: list[str] = []
    for row in root.iter():
        if _xml_local_name(row.tag) != "row":
            continue

        values: list[str] = []
        for cell in row:
            if _xml_local_name(cell.tag) != "c":
                continue

            cell_type = cell.attrib.get("t")
            raw_value = ""
            if cell_type == "inlineStr":
                raw_value = " ".join(
                    node.text or ""
                    for node in cell.iter()
                    if _xml_local_name(node.tag) == "t"
                )
            else:
                value_node = next(
                    (node for node in cell if _xml_local_name(node.tag) == "v"),
                    None,
                )
                raw_value = (
                    value_node.text
                    if value_node is not None and value_node.text
                    else ""
                )
                if cell_type == "s" and raw_value.isdigit():
                    index = int(raw_value)
                    raw_value = (
                        shared_strings[index]
                        if index < len(shared_strings)
                        else raw_value
                    )

            values.append(raw_value.strip())

        if any(values):
            rows.append("\t".join(values).rstrip())

    if not rows:
        return None
    return f"{sheet_name}:\n" + "\n".join(rows)


def _extract_xlsx_text(content: bytes) -> str | None:
    """读取 xlsx 单元格缓存值，失败时降级为不可读二进制附件。"""
    if not content:
        return ""

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            shared_strings = _extract_xlsx_shared_strings(archive)
            sheet_names = sorted(
                name
                for name in archive.namelist()
                if name.startswith("xl/worksheets/") and name.endswith(".xml")
            )
            sections = []
            for index, sheet_member in enumerate(sheet_names, start=1):
                with archive.open(sheet_member) as member:
                    sheet_text = _extract_xlsx_sheet_text(
                        member.read(), shared_strings, f"Sheet {index}"
                    )
                if sheet_text:
                    sections.append(sheet_text)
    except (OSError, RuntimeError, zipfile.BadZipFile):
        logger.warning("无法解析 AI 对话 xlsx 附件")
        return None

    text = "\n\n".join(sections).strip()
    if not text:
        return None
    return text[: settings.LLM_CHAT_MAX_TEXT_FILE_BYTES]


def _extract_pptx_text(content: bytes) -> str | None:
    """读取 pptx 幻灯片与备注文本，失败时降级为不可读二进制附件。"""
    if not content:
        return ""

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            sections: list[str] = []
            member_names = sorted(
                name
                for name in archive.namelist()
                if name.endswith(".xml")
                and any(name.startswith(prefix) for prefix in _PPTX_TEXT_PREFIXES)
            )
            for index, member_name in enumerate(member_names, start=1):
                with archive.open(member_name) as member:
                    member_text = _extract_plain_xml_text(member.read())
                if member_text:
                    sections.append(f"Slide {index}:\n{member_text}")
    except (OSError, RuntimeError, zipfile.BadZipFile):
        logger.warning("无法解析 AI 对话 pptx 附件")
        return None

    text = "\n\n".join(sections).strip()
    if not text:
        return None
    return text[: settings.LLM_CHAT_MAX_TEXT_FILE_BYTES]


def _extract_pdf_text(content: bytes) -> str | None:
    """使用 pypdf 读取 PDF 文本；扫描件或加密 PDF 可能只能返回元信息。"""
    if not content:
        return ""

    try:
        pypdf = importlib.import_module("pypdf")
        reader = pypdf.PdfReader(io.BytesIO(content))
        sections = []
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                sections.append(page_text)
    except Exception:
        logger.warning("无法解析 AI 对话 pdf 附件")
        return None

    text = "\n\n".join(sections).strip()
    if not text:
        return None
    return text[: settings.LLM_CHAT_MAX_TEXT_FILE_BYTES]


def _extract_upload_text(
    content: bytes, filename: str, content_type: str | None
) -> str | None:
    """按常见文件家族提取文本，未知格式尝试安全解码。"""
    if _is_docx_upload(filename, content_type):
        return _extract_docx_text(content)
    if _is_xlsx_upload(filename, content_type):
        return _extract_xlsx_text(content)
    if _is_pptx_upload(filename, content_type):
        return _extract_pptx_text(content)
    if _is_pdf_upload(filename, content_type):
        return _extract_pdf_text(content)
    if _is_text_upload(filename, content_type):
        text = _decode_text_upload(content) if content else ""
        return (
            text[: settings.LLM_CHAT_MAX_TEXT_FILE_BYTES] if text is not None else None
        )

    decoded_text = _decode_text_upload(content)
    return (
        decoded_text[: settings.LLM_CHAT_MAX_TEXT_FILE_BYTES]
        if decoded_text is not None
        else None
    )


async def _attachment_from_upload(
    upload: UploadFile, display_name: str
) -> AIChatAttachment:
    content = await upload.read()
    content_type = upload.content_type
    if _is_image_upload(display_name, content_type):
        media_type = (
            content_type or mimetypes.guess_type(display_name)[0] or "image/png"
        )
        encoded = base64.b64encode(content).decode("ascii")
        return AIChatAttachment(
            filename=display_name,
            content_type=media_type,
            size=len(content),
            image_data_url=f"data:{media_type};base64,{encoded}",
        )

    return AIChatAttachment(
        filename=display_name,
        content_type=content_type,
        size=len(content),
        text=_extract_upload_text(content, display_name, content_type),
    )


async def build_ai_chat_stream_request_from_multipart(
    form: FormData,
) -> AIChatStreamRequest:
    """把前端 multipart 对话请求转换为内部请求对象。

    1. 解析兼容 JSON 字段的表单参数
    2. 读取多文件/文件夹上传项并校验数量、总大小
    3. 将文本文件、图片和其他文件统一整理为本轮附件上下文
    """
    try:
        request_data: dict[str, Any] = {
            "session_id": _first_form_value(form, "session_id"),
            "message": _first_form_value(form, "message"),
            "model": _first_form_value(form, "model"),
            "temperature": _float_form_value(_first_form_value(form, "temperature")),
            "max_tokens": _int_form_value(_first_form_value(form, "max_tokens")),
            "system_prompt": _first_form_value(form, "system_prompt"),
            "thinking_mode": _first_form_value(form, "thinking_mode"),
            "enable_thinking": _bool_form_value(
                _first_form_value(form, "enable_thinking")
            ),
        }
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=AIChatMsg.REQUEST_BODY_INVALID,
        ) from exc

    uploads = _multipart_files(form)
    if len(uploads) > settings.LLM_CHAT_MAX_UPLOAD_FILES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=AIChatMsg.UPLOAD_FILE_TOO_MANY,
        )

    relative_paths = _multipart_relative_paths(form)
    attachments: list[AIChatAttachment] = []
    total_size = 0
    for index, upload in enumerate(uploads):
        display_name = _safe_display_name(
            relative_paths[index] if index < len(relative_paths) else upload.filename
        )
        attachment = await _attachment_from_upload(upload, display_name)
        total_size += attachment.size
        if total_size > settings.LLM_CHAT_MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=AIChatMsg.UPLOAD_FILE_TOO_LARGE,
            )
        attachments.append(attachment)

    request_data["attachments"] = attachments
    try:
        return AIChatStreamRequest.model_validate(request_data)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc


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
    user_attachments: list[AIChatAttachmentPublic],
    assistant_message: str,
) -> None:
    """完整流式响应结束后再写入 Redis，避免保存半截 assistant 回复。"""
    if not assistant_message:
        return

    next_history = _trim_history(
        [
            *history,
            AIChatMessage(
                role="user",
                content=user_message,
                attachments=user_attachments,
            ),
            AIChatMessage(role="assistant", content=assistant_message),
        ]
    )
    await redis.set(
        key,
        [_history_message_dump(message) for message in next_history],
        _session_ttl(),
    )


def _fallback_conversation_title(user_message: str, assistant_message: str) -> str:
    """模型标题生成不可用时的兜底标题。"""
    source = user_message.strip() or assistant_message.strip() or "新对话"
    first_line = next(
        (line.strip() for line in source.splitlines() if line.strip()),
        "新对话",
    )
    title = re.sub(r"\s+", " ", first_line).strip(" \"'`“”")
    if len(title) <= _TITLE_MAX_LENGTH:
        return title or "新对话"
    return f"{title[:_TITLE_MAX_LENGTH].rstrip()}..."


def _title_context(value: str) -> str:
    """限制标题生成上下文长度，避免把完整长对话再次提交给模型。"""
    normalized = re.sub(r"\s+", " ", value).strip()
    if len(normalized) <= _TITLE_CONTEXT_MAX_LENGTH:
        return normalized
    return normalized[:_TITLE_CONTEXT_MAX_LENGTH].rstrip()


def _normalize_generated_title(raw_title: str, fallback: str) -> str:
    """清洗模型返回，保证接口只写回短标题本身。"""
    title_text = re.sub(
        r"<think>.*?</think>",
        "",
        raw_title,
        flags=re.IGNORECASE | re.DOTALL,
    ).strip()
    title = next(
        (line.strip() for line in title_text.splitlines() if line.strip()),
        fallback,
    )
    title = re.sub(r"^(标题|对话标题|title)\s*[:：]\s*", "", title, flags=re.I)
    title = re.sub(r"\s+", " ", title).strip(" \"'`“”《》【】[]()（）")
    if not title or title.lower() in _GENERIC_TITLE_VALUES:
        title = fallback
    if len(title) <= _TITLE_MAX_LENGTH:
        return title
    return f"{title[:_TITLE_MAX_LENGTH].rstrip()}..."


def _conversation_message_to_history(
    message: Any,
) -> AIChatMessage | None:
    if message.role not in _PERSISTENT_MESSAGE_ROLES:
        return None
    role = cast(Literal["user", "assistant"], message.role)
    return AIChatMessage(
        role=role,
        content=message.content,
        attachments=_coerce_attachment_metadata(getattr(message, "attachments", [])),
    )


def _conversation_message_to_public(
    message: Any,
) -> AIChatConversationMessagePublic | None:
    if message.role not in _PERSISTENT_MESSAGE_ROLES:
        return None
    role = cast(Literal["user", "assistant"], message.role)
    reasoning_fields = _reasoning_payload_fields(message.reasoning_content)
    return AIChatConversationMessagePublic(
        id=message.id,
        role=role,
        content=message.content,
        attachments=_coerce_attachment_metadata(getattr(message, "attachments", [])),
        reasoning_title=reasoning_fields["reasoning_title"],
        reasoning_content=reasoning_fields["reasoning_content"],
        created_at=message.created_at,
    )


def _conversation_to_response(
    *,
    conversation: Any,
    messages: list[Any],
) -> AIChatConversationResponse:
    public_messages = [
        public_message
        for message in messages
        if (public_message := _conversation_message_to_public(message)) is not None
    ]
    return AIChatConversationResponse(
        id=conversation.id,
        session_id=str(conversation.id),
        title=conversation.title,
        messages=public_messages,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        last_message_at=conversation.last_message_at,
    )


def _load_persistent_history(
    *,
    session: Session,
    current_user: User,
    conversation_id: uuid.UUID,
) -> list[AIChatMessage] | None:
    conversation = crud.get_ai_chat_conversation_for_user(
        session,
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    if conversation is None:
        return None

    history = []
    for message in crud.list_ai_chat_messages(session, conversation_id=conversation.id):
        history_message = _conversation_message_to_history(message)
        if history_message is not None:
            history.append(history_message)
    return history


def _attachment_text_context(attachments: list[AIChatAttachment]) -> str:
    if not attachments:
        return ""

    sections = ["\n\n本轮用户上传的附件如下："]
    for index, attachment in enumerate(attachments, start=1):
        content_type = attachment.content_type or "unknown"
        sections.append(
            f"\n[{index}] {attachment.filename}\n"
            f"- MIME: {content_type}\n"
            f"- Size: {attachment.size} bytes"
        )
        if attachment.text is not None:
            sections.append(f"- Text content:\n{attachment.text}")
        elif attachment.image_data_url is not None:
            sections.append("- Image content is attached as image_url.")
        else:
            sections.append(
                "- Binary content is not directly readable; only metadata is available."
            )
    return "\n".join(sections)


def _user_message_content(request: AIChatStreamRequest) -> str | list[dict[str, Any]]:
    attachment_context = _attachment_text_context(request.attachments)
    text = f"{request.message}{attachment_context}"
    image_parts = [
        {"type": "image_url", "image_url": {"url": attachment.image_data_url}}
        for attachment in request.attachments
        if attachment.image_data_url is not None
    ]
    if not image_parts:
        return text
    return [{"type": "text", "text": text}, *image_parts]


def _request_messages(
    history: list[AIChatMessage], request: AIChatStreamRequest
) -> list[dict[str, Any]]:
    messages: list[AIChatMessage] = []
    if request.system_prompt and request.system_prompt.strip():
        messages.append(
            AIChatMessage(role="system", content=request.system_prompt.strip())
        )
    messages.extend(_trim_history(history))
    payload_messages: list[dict[str, Any]] = [
        {"role": message.role, "content": message.content} for message in messages
    ]
    payload_messages.append({"role": "user", "content": _user_message_content(request)})
    return payload_messages


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
    enable_thinking = request.resolved_enable_thinking
    if enable_thinking is not None:
        payload["chat_template_kwargs"] = {"enable_thinking": enable_thinking}
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


def _openai_title_payload(
    *,
    user_message: str,
) -> dict[str, Any]:
    """构造短标题生成请求，输入只保留用户原始提问。"""
    context = f"用户提问：{_title_context(user_message)}"
    return {
        "model": settings.LLM_CHAT_MODEL,
        "messages": [
            {"role": "system", "content": _TITLE_SYSTEM_PROMPT},
            {"role": "user", "content": context},
        ],
        "stream": False,
        "temperature": 0.2,
        "max_tokens": 32,
        "chat_template_kwargs": {"enable_thinking": False},
    }


def _extract_chat_message_content(payload: dict[str, Any]) -> str:
    """从 OpenAI-compatible 非流式响应里读取 message.content。"""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise _AIChatUpstreamError(AIChatMsg.UPSTREAM_RESPONSE_INVALID)
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise _AIChatUpstreamError(AIChatMsg.UPSTREAM_RESPONSE_INVALID)
    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise _AIChatUpstreamError(AIChatMsg.UPSTREAM_RESPONSE_INVALID)
    content = message.get("content")
    if not isinstance(content, str):
        raise _AIChatUpstreamError(AIChatMsg.UPSTREAM_RESPONSE_INVALID)
    return content


async def _generate_conversation_title(
    *,
    user_message: str,
) -> str:
    """用用户提问生成短标题；失败时使用本地兜底，不中断回答流。"""
    fallback = _fallback_conversation_title(user_message, "")
    payload = _openai_title_payload(user_message=user_message)
    timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
    url = f"{settings.LLM_API_BASE_URL.rstrip('/')}/chat/completions"
    headers = _openai_headers()
    headers["Accept"] = "application/json"

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code >= status.HTTP_400_BAD_REQUEST:
                await response.aread()
                raise _AIChatUpstreamError(AIChatMsg.UPSTREAM_REQUEST_FAILED)
            raw_title = _extract_chat_message_content(response.json())
    except (httpx.HTTPError, _AIChatUpstreamError, ValueError):
        logger.exception("AI 对话标题生成失败，使用本地兜底标题")
        return fallback

    return _normalize_generated_title(raw_title, fallback)


async def stream_ai_chat_service(
    *,
    redis: RedisService,
    current_user: User,
    request: AIChatStreamRequest,
    session: Session | None = None,
) -> AsyncIterator[str]:
    """代理 OpenAI-compatible 流式对话。

    1. 确定或创建当前用户隔离的持久化会话 ID
    2. 优先从 PostgreSQL 读取历史，兼容旧 Redis 临时历史
    3. 将上游 data chunk 转换为前端 SSE 事件
    4. 上游完整结束后再写回 user / assistant 历史
    """
    conversation_id = _parse_conversation_id(request.session_id)
    if session is not None:
        if conversation_id is None and request.session_id is None:
            conversation_id = uuid.uuid4()
        session_id = (
            str(conversation_id) if conversation_id is not None else _new_session_id()
        )
    else:
        session_id = request.session_id or _new_session_id()

    redis_key = _session_key(current_user, session_id)
    if session is not None and conversation_id is not None:
        persistent_history = _load_persistent_history(
            session=session,
            current_user=current_user,
            conversation_id=conversation_id,
        )
        if persistent_history is None and request.session_id is not None:
            yield _sse_event("error", {"message": AIChatMsg.SESSION_NOT_FOUND})
            return
        history = persistent_history or []
    else:
        history = await _load_history(redis, redis_key)

    should_generate_title = (
        session is not None and conversation_id is not None and not history
    )
    payload = _openai_payload(history, request)
    user_attachments = _attachment_public_metadata(request.attachments)
    should_emit_reasoning = request.should_emit_reasoning
    assistant_chunks: list[str] = []
    reasoning_chunks: list[str] = []
    generated_title: str | None = None

    yield _sse_event("session", {"session_id": session_id})

    try:
        async for event, delta in _iter_openai_deltas(payload):
            if event == "reasoning":
                reasoning_chunks.append(delta)
                if should_emit_reasoning:
                    reasoning_raw_content = "".join(reasoning_chunks)
                    yield _sse_event(
                        "reasoning",
                        {
                            "content": delta,
                            **_reasoning_payload_fields(reasoning_raw_content),
                        },
                    )
                continue

            if should_emit_reasoning:
                stripped_delta = _strip_duplicated_reasoning(
                    delta, "".join(reasoning_chunks)
                )
                if stripped_delta is None:
                    continue
                delta = stripped_delta

            if should_generate_title and generated_title is None:
                # 上游开始返回 content 时，reasoning 已结束；标题只根据用户提问生成。
                generated_title = await _generate_conversation_title(
                    user_message=request.message,
                )
                yield _sse_event(
                    "title",
                    {"session_id": session_id, "title": generated_title},
                )

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
    reasoning_message = "".join(reasoning_chunks) if should_emit_reasoning else None
    if assistant_message and session is not None and conversation_id is not None:
        title = generated_title or _fallback_conversation_title(
            request.message,
            assistant_message,
        )
        crud.append_ai_chat_exchange(
            session,
            conversation_id=conversation_id,
            user_id=current_user.id,
            title=title,
            user_message=request.message,
            assistant_message=assistant_message,
            user_attachments=[
                attachment.model_dump() for attachment in user_attachments
            ],
            reasoning_content=reasoning_message,
        )
    await _save_history(
        redis=redis,
        key=redis_key,
        history=history,
        user_message=request.message,
        user_attachments=user_attachments,
        assistant_message=assistant_message,
    )
    done_data: dict[str, Any] = {
        "session_id": session_id,
        "message": assistant_message,
    }
    if reasoning_message is not None:
        done_data["reasoning"] = reasoning_message
        done_data.update(_reasoning_payload_fields(reasoning_message))
    yield _sse_event("done", done_data)


def list_ai_chat_conversations_service(
    *,
    session: Session,
    current_user: User,
    page: int,
    page_size: int,
) -> PaginatedResponse[AIChatConversationListItem]:
    """读取当前用户的 AI 对话最近栏列表。"""
    conversations, total = crud.list_ai_chat_conversations(
        session,
        user_id=current_user.id,
        page=page,
        page_size=page_size,
    )
    return PaginatedResponse[AIChatConversationListItem](
        total=total,
        page=page,
        page_size=page_size,
        items=[
            AIChatConversationListItem(
                id=conversation.id,
                title=conversation.title,
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
                last_message_at=conversation.last_message_at,
            )
            for conversation in conversations
        ],
    )


def get_ai_chat_conversation_service(
    *,
    session: Session,
    current_user: User,
    conversation_id: uuid.UUID,
) -> AIChatConversationResponse:
    """读取当前用户的 AI 对话完整历史。"""
    conversation = crud.get_ai_chat_conversation_for_user(
        session,
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AIChatMsg.SESSION_NOT_FOUND,
        )
    messages = crud.list_ai_chat_messages(session, conversation_id=conversation.id)
    return _conversation_to_response(conversation=conversation, messages=messages)


def update_ai_chat_conversation_title_service(
    *,
    session: Session,
    current_user: User,
    conversation_id: uuid.UUID,
    title: str,
) -> AIChatConversationResponse:
    """修改当前用户的 AI 对话会话标题。"""
    normalized_title = re.sub(r"\s+", " ", title).strip()
    if not normalized_title:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=AIChatMsg.TITLE_REQUIRED,
        )
    conversation = crud.get_ai_chat_conversation_for_user(
        session,
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AIChatMsg.SESSION_NOT_FOUND,
        )
    conversation = crud.update_ai_chat_conversation_title(
        session,
        conversation=conversation,
        title=normalized_title,
    )
    messages = crud.list_ai_chat_messages(session, conversation_id=conversation.id)
    return _conversation_to_response(conversation=conversation, messages=messages)


def delete_ai_chat_conversation_service(
    *,
    session: Session,
    current_user: User,
    conversation_id: uuid.UUID,
) -> Message:
    """删除当前用户的 AI 对话会话和完整消息历史。"""
    conversation = crud.get_ai_chat_conversation_for_user(
        session,
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AIChatMsg.SESSION_NOT_FOUND,
        )
    crud.delete_ai_chat_conversation(session, conversation=conversation)
    return Message(message=AIChatMsg.SESSION_DELETED)


async def get_ai_chat_session_service(
    *,
    redis: RedisService,
    current_user: User,
    session_id: str,
    session: Session | None = None,
) -> AIChatSessionResponse:
    """读取当前登录用户的 AI 对话历史，优先返回持久化会话。"""
    conversation_id = _parse_conversation_id(session_id)
    if session is not None and conversation_id is not None:
        conversation = crud.get_ai_chat_conversation_for_user(
            session,
            conversation_id=conversation_id,
            user_id=current_user.id,
        )
        if conversation is not None:
            messages = [
                history_message
                for message in crud.list_ai_chat_messages(
                    session,
                    conversation_id=conversation.id,
                )
                if (history_message := _conversation_message_to_history(message))
                is not None
            ]
            return AIChatSessionResponse(
                session_id=session_id,
                title=conversation.title,
                messages=messages,
                ttl=-1,
            )

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
    *,
    redis: RedisService,
    current_user: User,
    session_id: str,
    session: Session | None = None,
) -> Message:
    """删除当前登录用户的 AI 对话历史，优先删除持久化会话。"""
    conversation_id = _parse_conversation_id(session_id)
    if session is not None and conversation_id is not None:
        conversation = crud.get_ai_chat_conversation_for_user(
            session,
            conversation_id=conversation_id,
            user_id=current_user.id,
        )
        if conversation is not None:
            crud.delete_ai_chat_conversation(session, conversation=conversation)
            await redis.delete(_session_key(current_user, session_id))
            return Message(message=AIChatMsg.SESSION_DELETED)

    redis_key = _session_key(current_user, session_id)
    if not await redis.delete(redis_key):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AIChatMsg.SESSION_NOT_FOUND,
        )
    return Message(message=AIChatMsg.SESSION_DELETED)
