"""AI 对话相关常量。"""


class AIChatMsg:
    """AI 对话接口用户侧提示消息。"""

    __slots__ = ()

    SESSION_NOT_FOUND = "AI 对话会话不存在或已过期"
    SESSION_DELETED = "AI 对话会话已删除"
    UPSTREAM_REQUEST_FAILED = "AI 服务请求失败，请稍后重试"
    UPSTREAM_RESPONSE_INVALID = "AI 服务响应格式异常"
    UPSTREAM_TIMEOUT = "AI 服务响应超时，请稍后重试"
