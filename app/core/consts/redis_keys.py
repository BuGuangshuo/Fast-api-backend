"""Redis key builders."""


class RedisKey:
    """Centralized Redis key namespace."""

    __slots__ = ()

    @staticmethod
    def framework_cache(key: str) -> str:
        return f"framework:cache:{key}"

    @staticmethod
    def ai_chat_session(user_id: str, session_id: str) -> str:
        """当前用户的 AI 对话临时历史。"""
        return f"ai_chat:session:{user_id}:{session_id}"

    @staticmethod
    def ai_chat_generation(user_id: str, generation_id: str) -> str:
        """可恢复 AI 回答的实时生成快照。"""
        return f"ai_chat:generation:{user_id}:{generation_id}"

    @staticmethod
    def ai_chat_generation_request(user_id: str, generation_id: str) -> str:
        """供 Celery worker 读取的 AI 回答请求快照。"""
        return f"ai_chat:generation_request:{user_id}:{generation_id}"

    @staticmethod
    def ai_chat_generation_cancelled(user_id: str, generation_id: str) -> str:
        """可恢复 AI 回答的用户取消标记。"""
        return f"ai_chat:generation_cancelled:{user_id}:{generation_id}"

    @staticmethod
    def ai_chat_conversation_generation(user_id: str, session_id: str) -> str:
        """持久化会话当前或最近一次可恢复生成任务 ID。"""
        return f"ai_chat:conversation_generation:{user_id}:{session_id}"

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
