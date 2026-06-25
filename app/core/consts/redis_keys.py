"""Redis key builders."""


class RedisKey:
    """Centralized Redis key namespace."""

    __slots__ = ()

    @staticmethod
    def framework_cache(key: str) -> str:
        return f"framework:cache:{key}"

    @staticmethod
    def access_token(user_id: str) -> str:
        """当前有效 access token。

        认证依赖会校验该 key 中保存的 token 是否与请求 token 完全一致。
        """
        return f"auth:access_token:{user_id}"

    @staticmethod
    def refresh_token(user_id: str) -> str:
        """当前有效 refresh token，用于刷新 access token 并支持单会话撤销。"""
        return f"auth:refresh_token:{user_id}"
