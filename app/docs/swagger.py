from fastapi import FastAPI
from fastapi.openapi.docs import (
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
from fastapi.responses import HTMLResponse


def setup_swagger(app: FastAPI) -> None:
    """注册自定义 Swagger UI 路由。"""

    @app.get("/docs", include_in_schema=False)
    async def custom_swagger_ui_html() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url=app.openapi_url or "/openapi.json",
            title=app.title,
            oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
            swagger_js_url="/static/swagger-ui-bundle.js",
            swagger_css_url="/static/swagger-ui.css",
        )

    @app.get(
        app.swagger_ui_oauth2_redirect_url or "/docs/oauth2-redirect",
        include_in_schema=False,
    )
    async def swagger_ui_redirect() -> HTMLResponse:
        return get_swagger_ui_oauth2_redirect_html()
