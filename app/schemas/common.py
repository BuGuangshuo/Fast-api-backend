"""通用组件 Schema。"""

from typing import Any

from pydantic import BaseModel, Field
from sqlmodel import SQLModel


class Message(SQLModel):
    """通用消息响应。"""

    message: str


class RtCacheResponse(BaseModel):
    """Redis 测试缓存响应。"""

    key: str
    value: Any
    ttl: int | None = None
    success: bool


class SelectOption(BaseModel):
    """下拉框选项。"""

    value: str = Field(description="选项值（用于接口传参）")
    label: str = Field(description="选项显示文本（用于前端展示）")
    description: str | None = Field(
        default=None, description="详细描述（用于 hover 展示）"
    )


class SelectOptionsResponse(BaseModel):
    """下拉框选项列表响应。"""

    options: list[SelectOption] = Field(description="选项列表")
