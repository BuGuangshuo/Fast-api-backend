import uuid
from collections.abc import Generator
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.core.consts import AuthMsg, AuthTokenType, RedisKey
from app.core.db import engine
from app.core.redis import RedisService, get_redis_service
from app.core.security import decode_token_payload
from app.models import User

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token"
)


def get_db() -> Generator[Session, None, None]:
    """每个请求创建一个短生命周期数据库 Session。"""
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_db)]


async def get_redis() -> RedisService:
    """Redis 依赖注入。"""
    return await get_redis_service()


RedisDep = Annotated[RedisService, Depends(get_redis)]
TokenDep = Annotated[str, Depends(oauth2_scheme)]


async def get_current_user(
    session: SessionDep,
    redis: RedisDep,
    token: TokenDep,
) -> User:
    """解析并校验当前用户。

    JWT 只提供用户声明；真正的会话有效性以 Redis 中的当前 access token 为准。
    校验通过后刷新 access token TTL，实现活跃会话滑动续期。
    """
    try:
        payload = decode_token_payload(token)
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMsg.INVALID_TOKEN,
            headers={"WWW-Authenticate": "Bearer"},
        )
    if payload.type != AuthTokenType.ACCESS_TOKEN or payload.sub is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMsg.INVALID_TOKEN_TYPE,
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = uuid.UUID(payload.sub)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMsg.INVALID_TOKEN,
            headers={"WWW-Authenticate": "Bearer"},
        )

    redis_key = RedisKey.access_token(str(user_id))
    cached_access_token = await redis.get(redis_key)
    if cached_access_token != token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMsg.REVOKED_TOKEN,
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = crud.get_user_by_id(session, user_id)
    if user is None:
        await redis.delete(redis_key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMsg.INVALID_TOKEN,
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        await redis.delete(redis_key)
        await redis.delete(RedisKey.refresh_token(str(user_id)))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AuthMsg.INACTIVE_USER,
        )

    await redis.expire(redis_key, settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_current_active_superuser(current_user: CurrentUser) -> User:
    """校验当前用户是否为超级管理员。"""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AuthMsg.INSUFFICIENT_PRIVILEGES,
        )
    return current_user


SuperuserDep = Annotated[User, Depends(get_current_active_superuser)]
