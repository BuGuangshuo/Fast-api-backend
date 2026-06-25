"""登录认证路由。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import CurrentUser, RedisDep, SessionDep
from app.core.consts import AuthMsg
from app.schemas import (
    AuthSessionResponse,
    LoginRequest,
    Message,
    RefreshAccessTokenRequest,
    Token,
    UserPublic,
)
from app.services.auth_service import (
    authenticate_user,
    create_login_session,
    get_login_session,
    logout_login_session,
    refresh_login_session,
)

router = APIRouter(prefix="/login", tags=["login"])


@router.post("/access-token", response_model=Token)
async def login_access_token(
    session: SessionDep,
    redis: RedisDep,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    """OAuth2 表单登录并签发 token。"""
    user = authenticate_user(session, form_data.username, form_data.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AuthMsg.INVALID_CREDENTIALS,
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AuthMsg.INACTIVE_USER,
        )
    return await create_login_session(session=session, redis=redis, user=user)


@router.post("", response_model=Token)
async def login_password(
    *,
    session: SessionDep,
    redis: RedisDep,
    request: LoginRequest,
) -> Token:
    """JSON 用户名密码登录并签发 token。"""
    user = authenticate_user(session, request.username, request.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AuthMsg.INVALID_CREDENTIALS,
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AuthMsg.INACTIVE_USER,
        )
    return await create_login_session(session=session, redis=redis, user=user)


@router.post("/refresh-token", response_model=Token)
async def refresh_access_token(
    *,
    session: SessionDep,
    redis: RedisDep,
    request: RefreshAccessTokenRequest,
) -> Token:
    """使用 refresh token 轮换登录会话。"""
    return await refresh_login_session(
        session=session, redis=redis, refresh_token=request.refresh_token
    )


@router.post("/logout", response_model=Message)
async def logout(
    *,
    redis: RedisDep,
    current_user: CurrentUser,
) -> Message:
    """撤销当前登录会话。"""
    await logout_login_session(redis=redis, user=current_user)
    return Message(message=AuthMsg.LOGOUT_SUCCESS)


@router.get("/me", response_model=UserPublic)
async def read_current_user(current_user: CurrentUser) -> UserPublic:
    """读取当前登录用户信息。"""
    return UserPublic.model_validate(current_user)


@router.get("/session", response_model=AuthSessionResponse)
async def read_current_session(
    *,
    redis: RedisDep,
    current_user: CurrentUser,
) -> AuthSessionResponse:
    """读取当前登录会话剩余 TTL。"""
    return await get_login_session(redis=redis, user=current_user)
