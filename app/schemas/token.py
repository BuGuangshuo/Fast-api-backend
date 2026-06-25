from typing import Literal

from pydantic import BaseModel, Field
from sqlmodel import SQLModel

TokenType = Literal["access_token", "refresh_token"]


class LoginRequest(BaseModel):
    """用户名密码登录请求。"""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class Token(SQLModel):
    """JWT token response."""

    access_token: str
    refresh_token: str = ""
    token_type: str = "bearer"
    expires_in: int


class TokenPayload(SQLModel):
    """JWT payload."""

    sub: str | None = None
    type: TokenType


class RefreshAccessTokenRequest(BaseModel):
    """Refresh token request."""

    refresh_token: str


class AuthSessionResponse(BaseModel):
    """当前登录会话信息。"""

    user_id: str
    username: str
    access_token_ttl: int
    refresh_token_ttl: int
