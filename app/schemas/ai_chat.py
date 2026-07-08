"""AI 对话 API Schema。"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# ==================== API Request/Response Schemas ====================

AIChatThinkingMode = Literal["auto", "thinking", "fast"]


class AIChatAttachmentPublic(BaseModel):
    """AI 对话历史中的附件展示信息。"""

    filename: str = Field(description="文件名或文件夹相对路径")
    content_type: str | None = Field(default=None, description="MIME 类型")
    size: int = Field(ge=0, description="文件大小，单位字节")


class AIChatMessage(BaseModel):
    """AI 对话消息。"""

    role: Literal["system", "user", "assistant"] = Field(description="消息角色")
    content: str = Field(min_length=1, description="消息内容")
    attachments: list[AIChatAttachmentPublic] = Field(
        default_factory=list,
        description="消息关联的附件展示信息",
    )


class AIChatAttachment(BaseModel):
    """本轮 AI 对话上传附件。"""

    filename: str = Field(min_length=1, description="文件名或文件夹相对路径")
    content_type: str | None = Field(default=None, description="MIME 类型")
    size: int = Field(ge=0, description="文件大小，单位字节")
    text: str | None = Field(default=None, description="可直接读取的文本内容")
    image_data_url: str | None = Field(default=None, description="图片 data URL")


class AIChatStreamRequest(BaseModel):
    """流式 AI 对话请求。"""

    session_id: str | None = Field(default=None, description="临时会话 ID")
    message: str = Field(min_length=1, description="本轮用户输入")
    model: str | None = Field(
        default=None, description="模型名称，不传则使用后端默认模型"
    )
    temperature: float | None = Field(default=None, ge=0, le=2, description="采样温度")
    max_tokens: int | None = Field(default=None, gt=0, description="最大输出 token 数")
    system_prompt: str | None = Field(default=None, description="本轮系统提示词")
    thinking_mode: AIChatThinkingMode | None = Field(
        default=None,
        description="思考模式：auto=自动，thinking=开启思考，fast=快速模式关闭思考；优先于兼容字段 enable_thinking",
    )
    enable_thinking: bool | None = Field(
        default=None,
        description="兼容旧前端的思考开关；新前端请改用 thinking_mode",
    )
    attachments: list[AIChatAttachment] = Field(
        default_factory=list,
        description="本轮随消息上传的附件，历史中仅保留文件名、类型和大小",
    )

    @property
    def resolved_enable_thinking(self) -> bool | None:
        """转换为上游 OpenAI-compatible 服务需要的思考开关。"""
        if self.thinking_mode == "thinking":
            return True
        if self.thinking_mode == "fast":
            return False
        if self.thinking_mode == "auto":
            return None
        return self.enable_thinking

    @property
    def should_emit_reasoning(self) -> bool:
        """判断 SSE 是否向前端透出 reasoning_content。"""
        if self.thinking_mode == "fast":
            return False
        if self.thinking_mode in {"auto", "thinking"}:
            return True
        return self.enable_thinking is True


class AIChatSessionCreatedResponse(BaseModel):
    """AI 对话临时会话创建结果。"""

    session_id: str = Field(description="临时会话 ID")
    ttl: int = Field(description="会话剩余有效秒数")


class AIChatSessionResponse(BaseModel):
    """AI 对话临时会话详情。"""

    session_id: str = Field(description="临时会话 ID")
    messages: list[AIChatMessage] = Field(description="会话消息历史")
    ttl: int = Field(description="会话剩余有效秒数")
    title: str | None = Field(default=None, description="持久化会话标题")


# ==================== Persistent Conversation Schemas ====================


class AIChatConversationListItem(BaseModel):
    """AI 对话最近栏会话列表项。"""

    id: uuid.UUID = Field(description="会话 ID")
    title: str = Field(description="会话标题")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")
    last_message_at: datetime = Field(description="最近消息时间")


class AIChatConversationMessagePublic(BaseModel):
    """AI 对话持久化消息。"""

    id: uuid.UUID = Field(description="消息 ID")
    role: Literal["user", "assistant"] = Field(description="消息角色")
    content: str = Field(description="消息内容")
    attachments: list[AIChatAttachmentPublic] = Field(
        default_factory=list,
        description="消息关联的附件展示信息",
    )
    reasoning_title: str | None = Field(default=None, description="模型思考标题")
    reasoning_content: str | None = Field(default=None, description="模型思考内容")
    created_at: datetime = Field(description="创建时间")


class AIChatConversationResponse(BaseModel):
    """AI 对话持久化会话详情。"""

    id: uuid.UUID = Field(description="会话 ID")
    session_id: str = Field(description="兼容流式接口的会话 ID")
    title: str = Field(description="会话标题")
    messages: list[AIChatConversationMessagePublic] = Field(description="完整消息历史")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")
    last_message_at: datetime = Field(description="最近消息时间")


class AIChatConversationUpdateRequest(BaseModel):
    """AI 对话会话名称更新请求。"""

    title: str = Field(min_length=1, max_length=128, description="新的会话标题")
