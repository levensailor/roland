"""Create and maintain the Roland/TM-2/WAVE folder layout on a mounted card."""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path

from app.config import Settings
from app.models import CardStatus, FolderInfo, SampleInfo
from app.services.converter import inspect_wav
from app.services.mounts import inspect_mount, remount_read_write, write_blocked_message


class SdCardError(Exception):
    """Invalid card path or TM-2 folder constraint."""


ROOT_FOLDER_LABEL = "(WAVE root)"


def ensure_writable(card_path: str, logger: logging.Logger, remount: bool = True) -> Path:
    root = resolve_card_path(card_path)
    mount = inspect_mount(root, logger)
    if remount and not mount.writable:
        try:
            mount = remount_read_write(root, logger)
        except RuntimeError as exc:
            raise SdCardError(str(exc)) from exc
    if not mount.writable:
        raise SdCardError(write_blocked_message(mount))
    return root


def remount_card(card_path: str, settings: Settings, logger: logging.Logger) -> CardStatus:
    root = resolve_card_path(card_path)
    try:
        remount_read_write(root, logger)
    except RuntimeError as exc:
        raise SdCardError(str(exc)) from exc
    return card_status(str(root), settings, logger)


def resolve_card_path(card_path: str) -> Path:
    path = Path(card_path).expanduser()
    if not card_path or not path.exists() or not path.is_dir():
        raise SdCardError("Select a mounted SD card folder that exists on this computer.")
    return path.resolve()


def wave_directory(card_path: Path, settings: Settings) -> Path:
    return card_path.joinpath(*settings.wave_parts)


def initialize_card(
    card_path: str,
    settings: Settings,
    logger: logging.Logger,
    create_recommended: bool = True,
    remount: bool = True,
) -> CardStatus:
    root = resolve_card_path(card_path)
    mount = inspect_mount(root, logger)
    if remount and not mount.writable:
        try:
            mount = remount_read_write(root, logger)
        except RuntimeError as exc:
            logger.info("Init remount skipped: %s", exc)
            if not wave_directory(root, settings).is_dir():
                raise SdCardError(str(exc)) from exc

    wave = wave_directory(root, settings)
    if mount.writable:
        try:
            wave.mkdir(parents=True, exist_ok=True)
            logger.info("Ensured WAVE root at %s", wave)
            if create_recommended:
                for folder_name in settings.default_folder_names:
                    safe_name = sanitize_name(folder_name, settings.max_filename_length)
                    target = wave / safe_name
                    target.mkdir(exist_ok=True)
                    logger.info("Ensured recommended folder %s", target)
        except OSError as exc:
            raise SdCardError(f"Could not write {settings.wave_root}: {exc}") from exc
    elif not wave.is_dir():
        raise SdCardError(write_blocked_message(mount))
    else:
        logger.info("WAVE tree already present at %s; card is not writable", wave)

    return card_status(str(root), settings, logger)


def card_status(card_path: str, settings: Settings, logger: logging.Logger) -> CardStatus:
    root = resolve_card_path(card_path)
    mount = inspect_mount(root, logger)
    wave = wave_directory(root, settings)
    folders = list_folders(wave, settings) if wave.is_dir() else []
    file_count = sum(folder.file_count for folder in folders)
    missing = [
        name
        for name in settings.default_folder_names
        if name not in {folder.name for folder in folders}
    ]
    warnings = list(mount.warnings)
    if wave.is_dir() and not mount.writable:
        warnings.append("The official WAVE folder is present, but writes will fail until the card is remounted read-write.")
    return CardStatus(
        selected_path=str(root),
        exists=True,
        writable=mount.writable,
        mount_readonly=mount.mount_readonly,
        media_readonly=mount.media_readonly,
        device=mount.device,
        fstype=mount.fstype,
        wave_root=settings.wave_root,
        wave_path=str(wave),
        wave_ready=wave.is_dir(),
        folder_count=max(len(folders) - 1, 0),
        file_count=file_count,
        remaining_folders=max(settings.max_folders - max(len(folders) - 1, 0), 0),
        folders=folders,
        recommended_folders=settings.default_folder_names,
        missing_recommended=missing,
        warnings=warnings,
    )


def list_folders(wave: Path, settings: Settings) -> list[FolderInfo]:
    folders = [
        FolderInfo(
            name=ROOT_FOLDER_LABEL,
            path=str(wave),
            file_count=_wav_count(wave),
            remaining_slots=max(settings.max_files_per_folder - _wav_count(wave), 0),
        )
    ]
    children = sorted(
        [child for child in wave.iterdir() if child.is_dir() and not child.name.startswith(".")],
        key=lambda item: item.name.lower(),
    )
    for child in children:
        count = _wav_count(child)
        folders.append(
            FolderInfo(
                name=child.name,
                path=str(child),
                file_count=count,
                remaining_slots=max(settings.max_files_per_folder - count, 0),
            )
        )
    return folders


def list_samples(card_path: str, settings: Settings, logger: logging.Logger) -> list[SampleInfo]:
    root = resolve_card_path(card_path)
    wave = wave_directory(root, settings)
    if not wave.is_dir():
        return []

    samples: list[SampleInfo] = []
    samples.extend(_samples_in_folder(wave, "", settings, logger))
    for child in sorted(wave.iterdir(), key=lambda item: item.name.lower()):
        if child.is_dir() and not child.name.startswith("."):
            samples.extend(_samples_in_folder(child, child.name, settings, logger))
    return samples


def create_folder(card_path: str, folder_name: str, settings: Settings, logger: logging.Logger) -> FolderInfo:
    root = ensure_writable(card_path, logger)
    wave = wave_directory(root, settings)
    if not wave.is_dir():
        raise SdCardError(f"{settings.wave_root} does not exist. Initialize the card first.")

    existing = [folder for folder in list_folders(wave, settings) if folder.name != ROOT_FOLDER_LABEL]
    if len(existing) >= settings.max_folders:
        raise SdCardError(f"The TM-2 only recognizes {settings.max_folders} folders inside WAVE.")

    safe_name = sanitize_name(folder_name, settings.max_filename_length)
    if not safe_name:
        raise SdCardError("Folder name must contain ASCII letters or numbers.")

    target = wave / safe_name
    if target.exists():
        raise SdCardError(f"Folder {safe_name} already exists.")
    target.mkdir()
    logger.info("Created folder %s", target)
    return FolderInfo(
        name=safe_name,
        path=str(target),
        file_count=0,
        remaining_slots=settings.max_files_per_folder,
    )


def destination_folder(
    card_path: str,
    folder_name: str,
    settings: Settings,
) -> Path:
    root = resolve_card_path(card_path)
    wave = wave_directory(root, settings)
    if not wave.is_dir():
        raise SdCardError(f"{settings.wave_root} does not exist. Initialize the card first.")

    if not folder_name or folder_name == ROOT_FOLDER_LABEL:
        return wave

    if "/" in folder_name or "\\" in folder_name:
        raise SdCardError("The TM-2 does not read folders nested more than one level under WAVE.")

    safe_name = sanitize_name(folder_name, settings.max_filename_length)
    target = wave / safe_name
    if not target.exists():
        raise SdCardError(f"Folder {safe_name} does not exist. Create it first.")
    return target


def unique_destination(folder: Path, desired_name: str, settings: Settings) -> Path:
    stem = sanitize_name(Path(desired_name).stem, settings.max_filename_length)
    if not stem:
        stem = "sample"
    candidate = folder / f"{stem}.wav"
    counter = 2
    while candidate.exists():
        suffix = f"_{counter}"
        trimmed = stem[: max(settings.max_filename_length - len(suffix), 1)]
        candidate = folder / f"{trimmed}{suffix}.wav"
        counter += 1
    return candidate


def assert_folder_capacity(folder: Path, incoming_count: int, settings: Settings) -> None:
    current = _wav_count(folder)
    if current + incoming_count > settings.max_files_per_folder:
        raise SdCardError(
            f"{folder.name} already has {current} files. "
            f"The TM-2 limit is {settings.max_files_per_folder} per folder."
        )


def delete_sample(card_path: str, folder: str, filename: str, settings: Settings, logger: logging.Logger) -> None:
    ensure_writable(card_path, logger)
    target_folder = destination_folder(card_path, folder, settings)
    safe_name = Path(filename).name
    if not safe_name.lower().endswith(".wav"):
        raise SdCardError("Only WAV files in the WAVE tree can be deleted from this app.")
    target = (target_folder / safe_name).resolve()
    wave = wave_directory(resolve_card_path(card_path), settings).resolve()
    if wave not in target.parents:
        raise SdCardError("Refusing to delete a file outside the WAVE folder.")
    if not target.exists():
        raise SdCardError(f"{safe_name} was not found.")
    target.unlink()
    logger.info("Deleted sample %s", target)


def sanitize_name(value: str, max_length: int) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_only = ascii_only.replace(" ", "_")
    ascii_only = re.sub(r"[^A-Za-z0-9._-]", "", ascii_only)
    ascii_only = re.sub(r"_+", "_", ascii_only).strip("._")
    return ascii_only[:max_length]


def _wav_count(folder: Path) -> int:
    return sum(1 for child in folder.iterdir() if child.is_file() and child.suffix.lower() == ".wav")


def _samples_in_folder(
    folder: Path,
    folder_label: str,
    settings: Settings,
    logger: logging.Logger,
) -> list[SampleInfo]:
    samples: list[SampleInfo] = []
    for child in sorted(folder.iterdir(), key=lambda item: item.name.lower()):
        if not child.is_file() or child.suffix.lower() != ".wav":
            continue
        info = {
            "sample_rate": None,
            "bit_depth": None,
            "channels": None,
            "duration_seconds": None,
            "size_bytes": child.stat().st_size,
        }
        try:
            info.update(inspect_wav(child))
        except Exception as exc:  # noqa: BLE001
            logger.info("Could not inspect %s: %s", child, exc)
        samples.append(
            SampleInfo(
                name=child.name,
                folder=folder_label or ROOT_FOLDER_LABEL,
                path=str(child),
                size_bytes=info["size_bytes"],
                sample_rate=info["sample_rate"],
                bit_depth=info["bit_depth"],
                channels=info["channels"],
                duration_seconds=info["duration_seconds"],
            )
        )
    return samples
