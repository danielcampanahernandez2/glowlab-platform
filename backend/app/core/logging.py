"""Structured Logging configuration for Glowlab."""
import logging
import logging.config
import sys
from app.core.config import settings


def setup_logging() -> None:
    """Configura el sistema de logging estándar con formato consistente."""
    log_level = logging.DEBUG if settings.DEBUG else logging.INFO

    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d - %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "json": {
                "format": '{"timestamp": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": "%(message)s"}',
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": sys.stdout,
                "formatter": "default",
                "level": log_level,
            },
        },
        "loggers": {
            "glowlab": {
                "handlers": ["console"],
                "level": log_level,
                "propagate": False,
            },
            "uvicorn": {
                "handlers": ["console"],
                "level": logging.INFO,
                "propagate": False,
            },
            "sqlalchemy.engine": {
                "handlers": ["console"],
                "level": logging.WARNING,
                "propagate": False,
            },
        },
        "root": {
            "handlers": ["console"],
            "level": log_level,
        },
    }

    logging.config.dictConfig(logging_config)
