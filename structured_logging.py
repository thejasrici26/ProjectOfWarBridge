import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone


REQUEST_ID_CONTEXT = ContextVar("warbridge_request_id", default=None)
LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


class JsonLogFormatter(logging.Formatter):
    SAFE_FIELDS = (
        "event",
        "request_id",
        "method",
        "path",
        "status_code",
        "duration_ms",
        "user_id",
        "role",
        "target_type",
        "target_id",
        "action",
        "outcome",
        "reason",
        "error_type",
        "db_dialect",
        "operation",
        "schema_version",
    )

    def format(self, record):
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in self.SAFE_FIELDS:
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        if "request_id" not in payload and REQUEST_ID_CONTEXT.get():
            payload["request_id"] = REQUEST_ID_CONTEXT.get()
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
