"""业务错误：路由统一转成 4xx JSON，code 可供前端/验证脚本精确判断。"""


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, extra: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.extra = extra or {}


class ConflictError(ApiError):
    def __init__(self, code: str, message: str, extra: dict | None = None):
        super().__init__(409, code, message, extra)


class UnprocessableError(ApiError):
    def __init__(self, code: str, message: str, extra: dict | None = None):
        super().__init__(422, code, message, extra)


class NotFoundError(ApiError):
    def __init__(self, code: str, message: str):
        super().__init__(404, code, message)


class BadRequestError(ApiError):
    def __init__(self, code: str, message: str, extra: dict | None = None):
        super().__init__(400, code, message, extra)
