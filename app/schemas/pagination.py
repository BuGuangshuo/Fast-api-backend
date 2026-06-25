"""通用分页响应模型。"""

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """通用分页响应模型。"""

    total: int = Field(description="总记录数")
    page: int = Field(ge=1, description="当前页码（从 1 开始）")
    page_size: int = Field(ge=1, description="每页记录数")
    items: list[T] = Field(description="数据列表")

    @property
    def total_pages(self) -> int:
        """计算总页数。"""
        return (
            (self.total + self.page_size - 1) // self.page_size if self.total > 0 else 0
        )

    @property
    def has_next(self) -> bool:
        """是否有下一页。"""
        return self.page < self.total_pages

    @property
    def has_prev(self) -> bool:
        """是否有上一页。"""
        return self.page > 1
