"""SD card status, initialization, remount, folders, and sample listing."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from app.config import Settings, get_settings
from app.errors import card_http_error
from app.instructions import build_instructions
from app.models import (
    CardStatus,
    CreateFolderRequest,
    DeleteSampleRequest,
    FolderInfo,
    InitCardRequest,
    InstructionsResponse,
    PublicConfig,
    RemountCardRequest,
    SampleInfo,
)
from app.services.sdcard import (
    ROOT_FOLDER_LABEL,
    SdCardError,
    card_status,
    create_folder,
    delete_sample,
    destination_folder,
    initialize_card,
    list_samples,
    remount_card,
)


def get_router(logger: logging.Logger) -> APIRouter:
    router = APIRouter()

    def settings_dep() -> Settings:
        return get_settings()

    @router.get("/config", response_model=PublicConfig)
    def public_config(settings: Settings = Depends(settings_dep)) -> PublicConfig:
        return PublicConfig(
            app_name=settings.app_name,
            author=settings.app_author,
            wave_root=settings.wave_root,
            sample_rate=settings.sample_rate,
            bit_depth=settings.bit_depth,
            default_channels=settings.default_channels,
            max_files_per_folder=settings.max_files_per_folder,
            max_folders=settings.max_folders,
            max_upload_mb=settings.max_upload_mb,
            default_folders=settings.default_folder_names,
            allowed_extensions=sorted(settings.allowed_extension_set),
            sdcard_path=settings.sdcard_path,
            root_folder_label=ROOT_FOLDER_LABEL,
        )

    @router.get("/instructions", response_model=InstructionsResponse)
    def instructions(settings: Settings = Depends(settings_dep)) -> InstructionsResponse:
        return build_instructions(settings)

    @router.get("/card/status", response_model=CardStatus)
    def status(
        card_path: str = Query(..., min_length=1),
        settings: Settings = Depends(settings_dep),
    ) -> CardStatus:
        try:
            return card_status(card_path, settings, logger)
        except SdCardError as exc:
            raise card_http_error(exc, logger) from exc

    @router.post("/card/init", response_model=CardStatus)
    def init_card(
        payload: InitCardRequest,
        settings: Settings = Depends(settings_dep),
    ) -> CardStatus:
        try:
            return initialize_card(
                payload.card_path,
                settings,
                logger,
                create_recommended=payload.create_recommended,
                remount=payload.remount,
            )
        except SdCardError as exc:
            raise card_http_error(exc, logger) from exc

    @router.post("/card/remount", response_model=CardStatus)
    def remount(
        payload: RemountCardRequest,
        settings: Settings = Depends(settings_dep),
    ) -> CardStatus:
        try:
            return remount_card(payload.card_path, settings, logger)
        except SdCardError as exc:
            raise card_http_error(exc, logger) from exc

    @router.post("/folders", response_model=FolderInfo)
    def add_folder(
        payload: CreateFolderRequest,
        settings: Settings = Depends(settings_dep),
    ) -> FolderInfo:
        try:
            return create_folder(payload.card_path, payload.folder_name, settings, logger)
        except SdCardError as exc:
            raise card_http_error(exc, logger) from exc

    @router.get("/samples", response_model=list[SampleInfo])
    def samples(
        card_path: str = Query(..., min_length=1),
        settings: Settings = Depends(settings_dep),
    ) -> list[SampleInfo]:
        try:
            return list_samples(card_path, settings, logger)
        except SdCardError as exc:
            raise card_http_error(exc, logger) from exc

    @router.get("/samples/audio")
    def sample_audio(
        card_path: str = Query(..., min_length=1),
        folder: str = Query(""),
        filename: str = Query(..., min_length=1),
        settings: Settings = Depends(settings_dep),
    ) -> FileResponse:
        try:
            target_folder = destination_folder(card_path, folder, settings)
            target = target_folder / Path(filename).name
            if not target.exists() or target.suffix.lower() != ".wav":
                raise SdCardError("WAV not found in the WAVE folder.")
        except SdCardError as exc:
            raise card_http_error(exc, logger) from exc
        return FileResponse(path=target, media_type="audio/wav", filename=target.name)

    @router.delete("/samples")
    def remove_sample(
        payload: DeleteSampleRequest,
        settings: Settings = Depends(settings_dep),
    ) -> dict:
        try:
            delete_sample(payload.card_path, payload.folder, payload.filename, settings, logger)
        except SdCardError as exc:
            raise card_http_error(exc, logger) from exc
        return {"deleted": payload.filename}

    return router
