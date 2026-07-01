"""AI 对话相关常量。"""


class AIChatMsg:
    """AI 对话接口用户侧提示消息。"""

    __slots__ = ()

    SESSION_NOT_FOUND = "AI 对话会话不存在或已过期"
    SESSION_DELETED = "AI 对话会话已删除"
    SESSION_UPDATED = "AI 对话会话名称已更新"
    TITLE_REQUIRED = "AI 对话会话名称不能为空"
    REQUEST_BODY_INVALID = "AI 对话请求格式不正确"
    UPLOAD_FILE_TOO_LARGE = "上传文件总大小超出限制"
    UPLOAD_FILE_TOO_MANY = "上传文件数量超出限制"
    UPSTREAM_REQUEST_FAILED = "AI 服务请求失败，请稍后重试"
    UPSTREAM_RESPONSE_INVALID = "AI 服务响应格式异常"
    UPSTREAM_TIMEOUT = "AI 服务响应超时，请稍后重试"
