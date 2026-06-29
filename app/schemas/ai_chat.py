"""AI 对话 API Schema。"""

from typing import Literal

from pydantic import BaseModel, Field

# ==================== API Request/Response Schemas ====================


class AIChatMessage(BaseModel):
    """AI 对话消息。"""

    role: Literal["system", "user", "assistant"] = Field(description="消息角色")
    content: str = Field(min_length=1, description="消息内容")


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
    enable_thinking: bool | None = Field(
        default=None,
        description="是否开启大模型思考模式；不传则使用上游服务默认值",
    )


class AIChatSessionCreatedResponse(BaseModel):
    """AI 对话临时会话创建结果。"""

    session_id: str = Field(description="临时会话 ID")
    ttl: int = Field(description="会话剩余有效秒数")


class AIChatSessionResponse(BaseModel):
    """AI 对话临时会话详情。"""

    session_id: str = Field(description="临时会话 ID")
    messages: list[AIChatMessage] = Field(description="会话消息历史")
    ttl: int = Field(description="会话剩余有效秒数")
