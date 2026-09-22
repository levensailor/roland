"""Shared HTTP error mapping so every card/sample route returns the same detail shape."""

from __future__ import annotations

import logging

from fastapi import HTTPException

from app.services.sdcard import SdCardError


def http_error(exc: Exception, logger: logging.Logger, status_code: int = 400) -> HTTPException:
    logger.info("API %s: %s", status_code, exc)
    return HTTPException(status_code=status_code, detail=str(exc))


def card_http_error(exc: SdCardError | Exception, logger: logging.Logger) -> HTTPException:
    return http_error(exc, logger, status_code=400)
