from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

_STANDARD_RECORD_KEYS: frozenset[str] = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
    }
)

_SENSITIVE_KEYWORDS: frozenset[str] = frozenset(
    {
        "authorization",
        "api_key",
        "cipher_text",
        "cookie",
        "credential",
        "dek",
        "master_password",
        "password",
        "secret",
        "token",
        "wrapped_dek",
    }
)


class SecureJSONFormatter(logging.Formatter):
    """Render log records as JSON while redacting sensitive values."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        for key, value in record.__dict__.items():
            if key.startswith("_") or key in _STANDARD_RECORD_KEYS:
                continue
            payload[key] = self._sanitize(key, value)

        if record.exc_info and record.exc_info[1] is not None:
            exc = record.exc_info[1]
            payload["exception"] = {
                "type": type(exc).__name__,
                "message": str(exc),
            }

        return json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))

    def _sanitize(self, key: str, value: Any) -> Any:
        key_lower = key.lower()
        if any(marker in key_lower for marker in _SENSITIVE_KEYWORDS):
            return "[REDACTED]"

        if isinstance(value, str) and len(value) > 512:
            return f"{value[:128]}...[TRUNCATED]"

        if isinstance(value, dict):
            return {
                item_key: self._sanitize(item_key, item_value)
                for item_key, item_value in value.items()
            }

        if isinstance(value, (list, tuple)):
            return [self._sanitize(key, item_value) for item_value in value]

        return value


def setup_logging(level: str = "INFO") -> None:
    """Configure structured logging for the application."""

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(SecureJSONFormatter())
    root_logger.addHandler(handler)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
