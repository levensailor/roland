"""Discover mounted volumes that may be TM-2 SD cards."""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

from app.config import Settings
from app.models import VolumeInfo
from app.services.mounts import inspect_mount


def list_volumes(settings: Settings, logger: logging.Logger) -> list[VolumeInfo]:
    seen: set[str] = set()
    volumes: list[VolumeInfo] = []
    for mount in _candidate_mounts():
        resolved = str(mount.resolve()) if mount.exists() else str(mount)
        if resolved in seen:
            continue
        seen.add(resolved)
        volumes.append(_describe_volume(mount, settings, logger))
    return volumes


def _candidate_mounts() -> list[Path]:
    mounts: list[Path] = []
    if sys.platform == "darwin":
        mounts.extend(_list_dir(Path("/Volumes")))
    elif sys.platform.startswith("linux"):
        user = os.environ.get("USER", "")
        mounts.extend(_list_dir(Path("/media") / user) if user else [])
        mounts.extend(_list_dir(Path("/run/media") / user) if user else [])
        mounts.extend(_list_dir(Path("/media")))
        mounts.extend(_list_dir(Path("/mnt")))
    elif sys.platform == "win32":
        mounts.extend(
            Path(f"{letter}:\\") for letter in "DEFGHIJKLMNOPQRSTUVWXYZ" if Path(f"{letter}:\\").exists()
        )
    return [path for path in mounts if path.exists() and path.is_dir()]


def _list_dir(root: Path) -> list[Path]:
    if not root.exists():
        return []
    ignored = {"Macintosh HD", "Macintosh HD - Data"}
    results = []
    for child in root.iterdir():
        if child.name.startswith(".") or child.name in ignored:
            continue
        results.append(child)
    return results


def _describe_volume(path: Path, settings: Settings, logger: logging.Logger) -> VolumeInfo:
    mount = inspect_mount(path, logger)
    wave_path = path.joinpath(*settings.wave_parts)
    free_bytes = None
    try:
        free_bytes = shutil.disk_usage(path).free
    except OSError as exc:
        logger.info("Could not read free space for %s: %s", path, exc)

    looks_like_sd = _looks_like_sd(path, settings)
    return VolumeInfo(
        name=path.name,
        path=str(path),
        writable=mount.writable,
        mount_readonly=mount.mount_readonly,
        media_readonly=mount.media_readonly,
        device=mount.device,
        looks_like_sd=looks_like_sd,
        has_wave_root=wave_path.is_dir(),
        free_bytes=free_bytes,
        warnings=mount.warnings,
    )


def _looks_like_sd(path: Path, settings: Settings) -> bool:
    if path.joinpath(*settings.wave_parts).exists():
        return True
    roland = path / settings.wave_parts[0] if settings.wave_parts else None
    if roland and roland.exists():
        return True
    markers = {"TM-2", "ROLAND", "Roland"}
    try:
        return any(child.name in markers for child in path.iterdir() if child.is_dir())
    except OSError:
        return False
