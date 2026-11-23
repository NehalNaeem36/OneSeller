from __future__ import annotations


class AppError(Exception):
    """Domain error rendered as {"error": {"code", "message"}}."""

    def __init__(self, status: int, code: str, message: str, extra: dict | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra or {}


def not_found(what: str = "Resource") -> AppError:
    return AppError(404, "not_found", f"{what} not found")


def forbidden(message: str = "You are not allowed to do that") -> AppError:
    return AppError(403, "forbidden", message)


def bad_request(message: str, code: str = "bad_request", **extra) -> AppError:
    return AppError(400, code, message, extra)
