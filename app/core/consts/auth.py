"""认证与会话相关常量。"""

from typing import Literal


class AuthTokenType:
    """JWT token type values."""

    __slots__ = ()

    ACCESS_TOKEN: Literal["access_token"] = "access_token"
    REFRESH_TOKEN: Literal["refresh_token"] = "refresh_token"


class AuthMsg:
    """认证接口用户侧提示消息。"""

    __slots__ = ()

    INVALID_CREDENTIALS = "用户名或密码错误"
    INVALID_TOKEN = "认证凭证无效"
    INVALID_TOKEN_TYPE = "Token 类型无效"
    REVOKED_TOKEN = "登录会话已失效，请重新登录"
    INACTIVE_USER = "用户已被禁用"
    INSUFFICIENT_PRIVILEGES = "权限不足"
    LOGOUT_SUCCESS = "已退出登录"
    REFRESH_TOKEN_EXPIRED = "刷新 token 无效或已过期"
