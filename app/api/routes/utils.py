"""基础工具路由。"""

from fastapi import APIRouter

from app.schemas import Message

router = APIRouter(prefix="/utils", tags=["utils"])


@router.get("/health-check/", response_model=Message)
def health_check() -> Message:
    """服务健康检查。"""
    return Message(message="ok")
