"""Mounted volume discovery."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.models import VolumeInfo
from app.services.volumes import list_volumes


def get_router(logger: logging.Logger) -> APIRouter:
    router = APIRouter(prefix="/api")

    def settings_dep() -> Settings:
        return get_settings()

    @router.get("/volumes", response_model=list[VolumeInfo])
    def volumes(settings: Settings = Depends(settings_dep)) -> list[VolumeInfo]:
        logger.info("Listing mounted volumes")
        return list_volumes(settings, logger)

    return router
