from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from passlib.context import CryptContext
from pydantic import ValidationError

from app.core.config import settings
from app.schemas import TokenType
from app.schemas.token import TokenPayload

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = "HS256"


def create_access_or_refresh_token(
    subject: str | Any, expires_delta: timedelta, token_type: TokenType
) -> str:
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode = {"exp": expire, "sub": str(subject), "type": token_type}
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_token_payload(token: str) -> TokenPayload:
    """解码并校验 JWT payload 结构。

    调用方继续负责判断 token type、Redis 会话状态和用户状态。
    """
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    try:
        return TokenPayload.model_validate(payload)
    except ValidationError as exc:
        raise jwt.InvalidTokenError from exc


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)
