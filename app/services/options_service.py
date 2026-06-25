"""下拉选项服务。"""

from app.schemas import SelectOption, SelectOptionsResponse


def list_framework_options() -> SelectOptionsResponse:
    """返回骨架项目的示例选项，便于保留 options 分层入口。"""
    return SelectOptionsResponse(
        options=[
            SelectOption(
                value="framework",
                label="基础框架",
                description="占位选项，后续业务模块可替换为真实枚举或配置来源",
            )
        ]
    )
