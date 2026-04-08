from __future__ import annotations

import json
import logging

from app.shared.logging_config import SecureJSONFormatter


def test_secure_json_formatter_redacts_sensitive_values() -> None:
    formatter = SecureJSONFormatter()
    record = logging.LogRecord(
        name="app",
        level=logging.INFO,
        pathname=__file__,
        lineno=12,
        msg="User action",
        args=(),
        exc_info=None,
    )
    record.token = "abc123"
    record.cipher_text = "super-secret-bytes"
    record.metadata = {"password": "hidden", "safe": "value"}

    payload = json.loads(formatter.format(record))

    assert payload["token"] == "[REDACTED]"
    assert payload["cipher_text"] == "[REDACTED]"
    assert payload["metadata"]["password"] == "[REDACTED]"
    assert payload["metadata"]["safe"] == "value"
