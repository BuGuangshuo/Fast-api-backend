import json
from typing import Any

import redis.asyncio as redis

from app.core.config import settings
from app.utils import get_logger

logger = get_logger(__name__)


class RedisManager:
    """Manage the shared Redis connection pool."""

    def __init__(self) -> None:
        self.redis_pool: redis.ConnectionPool | None = None
        self.redis_client: redis.Redis | None = None

    async def init_redis(self) -> None:
        """初始化 Redis 连接池。"""
        self.redis_pool = redis.ConnectionPool(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD,
            db=settings.REDIS_DB,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
            socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
            socket_connect_timeout=settings.REDIS_SOCKET_CONNECT_TIMEOUT,
            retry_on_timeout=settings.REDIS_RETRY_ON_TIMEOUT,
            decode_responses=True,
        )
        self.redis_client = redis.Redis(connection_pool=self.redis_pool)
        await self.redis_client.ping()
        logger.info("Redis连接成功")

    async def close_redis(self) -> None:
        """关闭 Redis 连接池。"""
        if self.redis_client:
            await self.redis_client.aclose()
        if self.redis_pool:
            await self.redis_pool.aclose()
        self.redis_client = None
        self.redis_pool = None
        logger.info("Redis连接已关闭")

    async def health_check(self) -> bool:
        """检查 Redis 是否可用。"""
        try:
            if self.redis_client is None:
                return False
            await self.redis_client.ping()
            return True
        except Exception:
            return False


class RedisService:
    """Small Redis helper used by routers and services."""

    def __init__(self, redis_client: redis.Redis) -> None:
        self.redis = redis_client

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """设置键值对。"""
        if ttl is None:
            ttl = settings.CACHE_DEFAULT_TTL
        if isinstance(value, dict | list):
            serialized = json.dumps(value, ensure_ascii=False)
        else:
            serialized = str(value)
        return bool(await self.redis.setex(key, ttl, serialized))

    async def get(self, key: str) -> Any:
        """读取键值并尽量还原 JSON。"""
        value = await self.redis.get(key)
        if value is None:
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    async def delete(self, key: str) -> bool:
        """删除 key。"""
        return bool(await self.redis.delete(key))

    async def ttl(self, key: str) -> int:
        """读取 key 的剩余过期时间。"""
        return int(await self.redis.ttl(key))

    async def expire(self, key: str, ttl: int) -> bool:
        """刷新 key 的过期时间。"""
        return bool(await self.redis.expire(key, ttl))


redis_manager = RedisManager()


async def get_redis_service() -> RedisService:
    """FastAPI dependency helper for RedisService."""
    if redis_manager.redis_client is None:
        await redis_manager.init_redis()
    if redis_manager.redis_client is None:
        raise RuntimeError("Redis client is not initialized")
    return RedisService(redis_manager.redis_client)
