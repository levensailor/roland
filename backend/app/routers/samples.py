"""Upload and convert audio onto the TM-2 WAVE tree."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.config import Settings, get_settings
from app.models import UploadResponse, UploadResult
from app.services.converter import ConversionError, convert_to_tm2_wav
from app.services.sdcard import (
    SdCardError,
    assert_folder_capacity,
    destination_folder,
    resolve_card_path,
    unique_destination,
)


def get_router(logger: logging.Logger) -> APIRouter:
    router = APIRouter(prefix="/api")

    def settings_dep() -> Settings:
        return get_settings()

    @router.post("/samples/upload", response_model=UploadResponse)
    async def upload_samples(
        card_path: str = Form(...),
        folder: str = Form(""),
        channels: str = Form(""),
        files: list[UploadFile] = File(...),
        settings: Settings = Depends(settings_dep),
    ) -> UploadResponse:
        if not files:
            raise HTTPException(status_code=400, detail="Drop at least one audio file.")

        channel_mode = (channels or settings.default_channels).strip().lower()
        if channel_mode not in {"auto", "mono", "stereo"}:
            raise HTTPException(status_code=400, detail="channels must be auto, mono, or stereo.")

        try:
            resolve_card_path(card_path)
            target_folder = destination_folder(card_path, folder, settings)
            assert_folder_capacity(target_folder, len(files), settings)
        except SdCardError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        results: list[UploadResult] = []
        errors: list[str] = []

        for upload in files:
            original_name = upload.filename or "sample"
            suffix = Path(original_name).suffix.lower()
            if suffix not in settings.allowed_extension_set:
                errors.append(f"{original_name}: unsupported type {suffix or '(none)'}")
                continue

            try:
                payload = await upload.read()
                if len(payload) > settings.max_upload_bytes:
                    errors.append(
                        f"{original_name}: larger than {settings.max_upload_mb} MB upload limit."
                    )
                    continue

                destination = unique_destination(target_folder, original_name, settings)
                with tempfile.NamedTemporaryFile(
                    prefix="tm2_upload_",
                    suffix=suffix or ".bin",
                    delete=False,
                ) as temp_handle:
                    temp_handle.write(payload)
                    temp_path = Path(temp_handle.name)

                try:
                    probe = convert_to_tm2_wav(
                        source_path=temp_path,
                        destination_path=destination,
                        settings=settings,
                        logger=logger,
                        channels_mode=channel_mode,
                    )
                finally:
                    temp_path.unlink(missing_ok=True)

                results.append(
                    UploadResult(
                        original_name=original_name,
                        saved_name=destination.name,
                        folder=target_folder.name if target_folder.name != settings.wave_parts[-1] else "",
                        path=str(destination),
                        converted=suffix != ".wav"
                        or probe["sample_rate"] != settings.sample_rate
                        or probe["bit_depth"] != settings.bit_depth,
                        sample_rate=probe["sample_rate"],
                        bit_depth=probe["bit_depth"],
                        channels=probe["channels"],
                        duration_seconds=probe["duration_seconds"],
                        message="Wrote TM-2 PCM WAV with metadata removed.",
                    )
                )
            except (ConversionError, SdCardError, OSError) as exc:
                logger.error("Upload failed for %s: %s", original_name, exc)
                errors.append(f"{original_name}: {exc}")

        if not results and errors:
            raise HTTPException(status_code=400, detail=" ".join(errors))

        folder_label = folder or target_folder.name
        return UploadResponse(
            card_path=card_path,
            folder=folder_label,
            results=results,
            errors=errors,
        )

    return router
