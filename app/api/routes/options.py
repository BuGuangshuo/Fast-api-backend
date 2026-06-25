"""下拉选项路由。"""

from fastapi import APIRouter

from app.schemas import SelectOptionsResponse
from app.services.options_service import list_framework_options

router = APIRouter(prefix="/options", tags=["options"])


@router.get("/framework", response_model=SelectOptionsResponse)
def list_framework_options_endpoint() -> SelectOptionsResponse:
    """返回骨架项目预置的示例下拉项。"""
    return list_framework_options()
