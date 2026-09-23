"""Inspect and safely remount SD card volumes. Never unmount; a failed remount must leave the card mounted."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class MountState:
    path: Path
    device: str = ""
    fstype: str = ""
    options: list[str] = field(default_factory=list)
    mount_readonly: bool = False
    media_readonly: bool = False
    writable: bool = False
    warnings: list[str] = field(default_factory=list)


def inspect_mount(path: Path, logger: logging.Logger) -> MountState:
    resolved = path.resolve()
    state = MountState(path=resolved)
    entry = _mount_entry_for(resolved)
    if entry:
        state.device = entry["device"]
        state.fstype = entry["fstype"]
        state.options = entry["options"]
        state.mount_readonly = "read-only" in entry["options"] or "ro" in entry["options"]

    state.media_readonly = _media_is_readonly(resolved, logger)
    access_ok = os.access(resolved, os.W_OK)
    state.writable = access_ok and not state.mount_readonly and not state.media_readonly

    if state.media_readonly:
        state.warnings.append(
            "The SD card lock switch is on. Slide it off LOCK, eject the card, and remount it."
        )
    elif state.mount_readonly:
        state.warnings.append(
            "macOS mounted this card read-only (dirty FAT from a hot eject). "
            "Remount RW cannot flip FSKit mounts — eject in Finder, run Disk Utility First Aid, "
            "reinsert, and keep the TM-2 powered off when you remove the card."
        )
    elif not access_ok:
        state.warnings.append("This path is not writable by the current user.")
    return state


def remount_read_write(path: Path, logger: logging.Logger) -> MountState:
    """Ask the OS to flip the existing mount to read-write. Do not unmount."""
    before = inspect_mount(path, logger)
    if before.writable:
        return before
    if before.media_readonly:
        raise RuntimeError(
            "The SD card media is locked. Slide the write-protect switch off LOCK and remount the card."
        )
    if not before.device:
        raise RuntimeError(f"{path} is not a mounted volume.")

    command = _remount_command(path, before)
    logger.info("Attempting read-write remount: %s", " ".join(command))
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    after = inspect_mount(path, logger)
    if completed.returncode == 0 and after.writable:
        logger.info("Remounted %s read-write on %s", path, after.device)
        return after

    detail = (completed.stderr or completed.stdout or "remount failed").strip()
    logger.info("Remount did not make %s writable: %s", path, detail)
    raise RuntimeError(_readonly_recovery_message(path, before, detail))


def _readonly_recovery_message(path: Path, state: MountState, detail: str) -> str:
    device = state.device or "the SD device"
    return (
        f"Could not remount {path} read-write ({detail}). "
        "This is not the plastic lock switch — macOS mounted a dirty FAT volume read-only "
        "(usually after pulling the card while the TM-2 was still powered on). "
        f"Do this: 1) Eject {path} in Finder (or physically remove and reinsert the card). "
        "2) Open Disk Utility → select the TM-2 volume → First Aid. "
        f"Or in Terminal: diskutil unmount {path} && diskutil repairVolume {device} && diskutil mount {device}. "
        "3) Power the TM-2 off before removing the card next time. "
        "Remount RW never unmounts for you — a failed remount must leave the card visible."
    )


def write_blocked_message(state: MountState) -> str:
    if state.warnings:
        return " ".join(state.warnings)
    return f"{state.path} is not writable."


def _mount_entry_for(path: Path) -> dict | None:
    matches: list[dict] = []
    for entry in _parse_mount_table():
        mountpoint = Path(entry["mountpoint"]).resolve()
        if path == mountpoint or mountpoint in path.parents:
            entry["mountpoint_path"] = mountpoint
            matches.append(entry)
    if not matches:
        return None
    matches.sort(key=lambda item: len(str(item["mountpoint_path"])), reverse=True)
    return matches[0]


def _parse_mount_table() -> list[dict]:
    completed = subprocess.run(["mount"], capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        return []
    pattern = re.compile(r"^(\S+) on (.+) \(([^)]+)\)\s*$")
    entries: list[dict] = []
    for line in completed.stdout.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        device, mountpoint, meta = match.groups()
        parts = [item.strip() for item in meta.split(",") if item.strip()]
        fstype = parts[0] if parts else ""
        options = [item.lower() for item in parts[1:]]
        entries.append(
            {
                "device": device,
                "mountpoint": mountpoint,
                "fstype": fstype,
                "options": options,
            }
        )
    return entries


def _media_is_readonly(path: Path, logger: logging.Logger) -> bool:
    if sys.platform != "darwin":
        return False
    completed = subprocess.run(
        ["diskutil", "info", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        logger.info("diskutil info failed for %s: %s", path, completed.stderr.strip())
        return False
    for line in completed.stdout.splitlines():
        if "Media Read-Only" in line:
            return line.strip().lower().endswith("yes")
    return False


def _remount_command(path: Path, state: MountState) -> list[str]:
    if sys.platform == "darwin":
        return ["mount", "-uw", str(path)]
    if state.device:
        return ["mount", "-o", "remount,rw", state.device, str(path)]
    return ["mount", "-o", "remount,rw", str(path)]
