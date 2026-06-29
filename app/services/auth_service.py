"""认证与登录会话 Service。"""

import uuid
from datetime import timedelta

import jwt
from fastapi import HTTPException, status
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.core.consts import AuthMsg, AuthTokenType, RedisKey
from app.core.redis import RedisService
from app.core.security import (
    create_access_or_refresh_token,
    decode_token_payload,
    verify_password,
)
from app.models import User
from app.schemas import AuthSessionResponse, Token


def _access_token_delta() -> timedelta:
    return timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)


def _refresh_token_delta() -> timedelta:
    return timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES)


def _seconds(delta: timedelta) -> int:
    return int(delta.total_seconds())


def _normalize_username(username: str) -> str:
    return username.strip()


def authenticate_user(session: Session, username: str, password: str) -> User | None:
    """校验用户名密码。

    只负责身份核验，不签发 token；这样 JSON 登录和 OAuth2 表单登录可以复用同一逻辑。
    """
    user = crud.get_user_by_username(session, _normalize_username(username))
    if user is None:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


async def create_login_session(
    *, session: Session, redis: RedisService, user: User
) -> Token:
    """创建登录会话并签发 access / refresh token。

    1. 生成一组新的 JWT
    2. 写入 Redis 当前有效 token，实现同用户单会话
    3. 回写最近登录时间，便于审计展示
    """
    user_id = str(user.id)
    access_delta = _access_token_delta()
    refresh_delta = _refresh_token_delta()
    access_token = create_access_or_refresh_token(
        user_id, access_delta, AuthTokenType.ACCESS_TOKEN
    )
    refresh_token = create_access_or_refresh_token(
        user_id, refresh_delta, AuthTokenType.REFRESH_TOKEN
    )

    await redis.set(
        RedisKey.access_token(user_id), access_token, _seconds(access_delta)
    )
    await redis.set(
        RedisKey.refresh_token(user_id), refresh_token, _seconds(refresh_delta)
    )
    crud.update_user_last_login(session, user)

    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=_seconds(access_delta),
    )


async def refresh_login_session(
    *, session: Session, redis: RedisService, refresh_token: str
) -> Token:
    """使用 refresh token 轮换登录会话。

    Refresh token 也必须与 Redis 中的当前会话一致；刷新成功后同时轮换 access
    和 refresh，旧 refresh token 立即失效。
    """
    try:
        payload = decode_token_payload(refresh_token)
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMsg.REFRESH_TOKEN_EXPIRED,
        )
    if payload.type != AuthTokenType.REFRESH_TOKEN or payload.sub is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMsg.INVALID_TOKEN_TYPE,
        )

    try:
        user_id = uuid.UUID(payload.sub)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMsg.INVALID_TOKEN,
        )

    cached_refresh_token = await redis.get(RedisKey.refresh_token(str(user_id)))
    if cached_refresh_token != refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMsg.REVOKED_TOKEN,
        )

    user = crud.get_user_by_id(session, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMsg.INVALID_TOKEN,
        )
    if not user.is_active:
        await redis.delete(RedisKey.access_token(str(user_id)))
        await redis.delete(RedisKey.refresh_token(str(user_id)))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AuthMsg.INACTIVE_USER,
        )

    return await create_login_session(session=session, redis=redis, user=user)


async def logout_login_session(*, redis: RedisService, user: User) -> None:
    """撤销当前用户登录会话。"""
    user_id = str(user.id)
    await redis.delete(RedisKey.access_token(user_id))
    await redis.delete(RedisKey.refresh_token(user_id))


async def get_login_session(*, redis: RedisService, user: User) -> AuthSessionResponse:
    """返回当前登录会话 TTL 信息。"""
    user_id = str(user.id)
    access_ttl = await redis.ttl(RedisKey.access_token(user_id))
    refresh_ttl = await redis.ttl(RedisKey.refresh_token(user_id))
    return AuthSessionResponse(
        user_id=user_id,
        username=user.username,
        access_token_ttl=access_ttl,
        refresh_token_ttl=refresh_ttl,
    )
