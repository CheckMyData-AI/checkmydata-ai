"""Structured logging configuration with workflow_id and request_id correlation."""

import json
import logging
import logging.config
from datetime import UTC, datetime

from app.core.workflow_tracker import request_id_var, workflow_id_var


class CorrelationFilter(logging.Filter):
    """Injects workflow_id and request_id from contextvars into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.workflow_id = workflow_id_var.get(None) or ""  # type: ignore[attr-defined]
        record.request_id = request_id_var.get(None) or ""  # type: ignore[attr-defined]
        return True


class JSONFormatter(logging.Formatter):
    """Structured JSON log format for production."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        wf_id = getattr(record, "workflow_id", "")
        if wf_id:
            entry["workflow_id"] = wf_id
        req_id = getattr(record, "request_id", "")
        if req_id:
            entry["request_id"] = req_id
        if record.exc_info and record.exc_info[1]:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


class ReadableFormatter(logging.Formatter):
    """Human-readable format for local development."""

    def format(self, record: logging.LogRecord) -> str:
        wf_id = getattr(record, "workflow_id", "")
        req_id = getattr(record, "request_id", "")
        tag = ""
        if wf_id:
            tag = f" [{wf_id[:8]}]"
        elif req_id:
            tag = f" [r:{req_id[:8]}]"
        ts = datetime.fromtimestamp(record.created, tz=UTC).strftime("%H:%M:%S.%f")[:-3]
        base = f"{ts} {record.levelname:7s}{tag} {record.name}: {record.getMessage()}"
        if record.exc_info and record.exc_info[1]:
            base += "\n" + self.formatException(record.exc_info)
        return base


def configure_logging(json_format: bool = False, level: str = "INFO") -> None:
    formatter_class = (
        "app.core.logging_config.JSONFormatter"
        if json_format
        else "app.core.logging_config.ReadableFormatter"
    )

    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "correlation": {"()": "app.core.logging_config.CorrelationFilter"},
        },
        "formatters": {
            "default": {"()": formatter_class},
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "filters": ["correlation"],
                "stream": "ext://sys.stdout",
            },
        },
        "root": {
            "level": level,
            "handlers": ["console"],
        },
        "loggers": {
            "uvicorn": {"level": "INFO", "handlers": ["console"], "propagate": False},
            "uvicorn.access": {"level": "WARNING", "handlers": ["console"], "propagate": False},
            "sqlalchemy.engine": {"level": "WARNING", "handlers": ["console"], "propagate": False},
            "asyncssh": {"level": "WARNING", "handlers": ["console"], "propagate": False},
            "httpx": {"level": "WARNING", "handlers": ["console"], "propagate": False},
            "httpcore": {"level": "WARNING", "handlers": ["console"], "propagate": False},
            "chromadb": {"level": "WARNING", "handlers": ["console"], "propagate": False},
            "alembic": {"level": "INFO", "handlers": ["console"], "propagate": False},
            "aiosqlite": {"level": "WARNING", "handlers": ["console"], "propagate": False},
            "hpack": {"level": "WARNING", "handlers": ["console"], "propagate": False},
        },
    }
    logging.config.dictConfig(config)
