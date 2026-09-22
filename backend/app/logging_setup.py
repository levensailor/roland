"""Console and rotating file logging with EST timestamps, line numbers, and function names."""

import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler
from zoneinfo import ZoneInfo

from app.config import Settings


class LocalizedFormatter(logging.Formatter):
    """Format log times in a configured local timezone."""

    def __init__(self, fmt: str, timezone_name: str) -> None:
        super().__init__(fmt=fmt)
        self.zone = ZoneInfo(timezone_name)

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        localized = datetime.fromtimestamp(record.created, tz=self.zone)
        if datefmt:
            return localized.strftime(datefmt)
        return localized.strftime("%Y-%m-%d %H:%M:%S %Z")


def configure_logging(settings: Settings) -> logging.Logger:
    """Attach rotating file and console handlers to the application logger."""
    settings.log_directory.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(settings.app_name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    formatter = LocalizedFormatter(
        fmt="%(asctime)s | %(levelname)s | %(funcName)s | line %(lineno)d | %(message)s",
        timezone_name=settings.log_timezone,
    )

    file_handler = RotatingFileHandler(
        filename=settings.log_file_path,
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger
