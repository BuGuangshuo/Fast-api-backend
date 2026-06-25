"""Redis 测试路由。"""

from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.api.deps import RedisDep
from app.core.consts import CommonMsg, RedisKey
from app.schemas import RtCacheResponse

router = APIRouter(prefix="/test-redis", tags=["test-redis"])


@router.post("/cache/set", response_model=RtCacheResponse)
async def set_cache(
    *,
    key: str,
    value: Any,
    redis: RedisDep,
    ttl: int | None = None,
) -> RtCacheResponse:
    """设置测试缓存。"""
    redis_key = RedisKey.framework_cache(key)
    success = await redis.set(redis_key, value, ttl)
    return RtCacheResponse(key=key, value=value, ttl=ttl, success=success)


@router.get("/cache/get/{key}", response_model=RtCacheResponse)
async def get_cache(key: str, redis: RedisDep) -> RtCacheResponse:
    """读取测试缓存。"""
    redis_key = RedisKey.framework_cache(key)
    value = await redis.get(redis_key)
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=CommonMsg.CACHE_NOT_FOUND,
        )
    ttl = await redis.ttl(redis_key)
    return RtCacheResponse(key=key, value=value, ttl=ttl, success=True)


@router.delete("/cache/delete/{key}")
async def delete_cache(key: str, redis: RedisDep) -> dict[str, str]:
    """删除测试缓存。"""
    redis_key = RedisKey.framework_cache(key)
    success = await redis.delete(redis_key)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=CommonMsg.CACHE_NOT_FOUND,
        )
    return {"message": CommonMsg.CACHE_DELETED}
