"""Public sample library search and import routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from app.config import Settings, get_settings
from app.errors import http_error
from app.models import (
    LibraryImportRequest,
    LibrarySearchResponse,
    LibrarySourcesResponse,
    UploadResult,
)
from app.services.library import (
    FOLDER_PRESETS,
    LibraryError,
    import_library_sample,
    list_sources,
    resolve_waves_file,
    search_library,
)
from app.services.sdcard import SdCardError


def get_router(logger: logging.Logger) -> APIRouter:
    router = APIRouter(prefix="/library")

    def settings_dep() -> Settings:
        return get_settings()

    @router.get("/sources", response_model=LibrarySourcesResponse)
    def sources(settings: Settings = Depends(settings_dep)) -> LibrarySourcesResponse:
        return LibrarySourcesResponse(
            license_mode=settings.library_license_mode,
            sources=list_sources(settings),
            presets=FOLDER_PRESETS,
        )

    @router.get("/search", response_model=LibrarySearchResponse)
    def search(
        q: str = Query("", alias="q"),
        folder: str = Query(""),
        source: str = Query("catalog"),
        page: int = Query(1, ge=1),
        settings: Settings = Depends(settings_dep),
    ) -> LibrarySearchResponse:
        try:
            return search_library(
                settings,
                logger,
                query=q,
                folder=folder,
                source=source,
                page=page,
            )
        except LibraryError as exc:
            raise http_error(exc, logger) from exc

    @router.get("/audio")
    def library_audio(
        source: str = Query(...),
        sample_id: str = Query(..., alias="id"),
        settings: Settings = Depends(settings_dep),
    ) -> FileResponse:
        if source.strip().lower() != "waves":
            raise http_error(LibraryError("Preview is only available for Waves Local."), logger)
        try:
            target = resolve_waves_file(settings, sample_id)
        except LibraryError as exc:
            raise http_error(exc, logger) from exc
        return FileResponse(path=target, media_type=_audio_media_type(target), filename=target.name)

    @router.post("/import", response_model=UploadResult)
    def import_sample(
        payload: LibraryImportRequest,
        settings: Settings = Depends(settings_dep),
    ) -> UploadResult:
        try:
            result = import_library_sample(
                settings,
                logger,
                card_path=payload.card_path,
                folder=payload.folder,
                source=payload.source,
                sample_id=payload.id,
                channels=payload.channels,
                remount=payload.remount,
            )
        except (LibraryError, SdCardError) as exc:
            raise http_error(exc, logger) from exc
        return UploadResult(
            original_name=result["original_name"],
            saved_name=result["saved_name"],
            folder=result["folder"],
            path=result["path"],
            converted=result["converted"],
            sample_rate=result["sample_rate"],
            bit_depth=result["bit_depth"],
            channels=result["channels"],
            duration_seconds=result["duration_seconds"],
            message=result["message"],
        )

    return router


def _audio_media_type(path) -> str:
    suffix = path.suffix.lower()
    return {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".flac": "audio/flac",
        ".ogg": "audio/ogg",
        ".oga": "audio/ogg",
        ".aif": "audio/aiff",
        ".aiff": "audio/aiff",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
        ".caf": "audio/x-caf",
    }.get(suffix, "application/octet-stream")
