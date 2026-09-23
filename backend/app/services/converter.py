"""Convert arbitrary audio to TM-2-safe 16-bit 44.1 kHz PCM WAV without metadata."""

from __future__ import annotations

import logging
import os
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

from app.config import Settings

# copyfile(3) stores extended attributes as ._* AppleDouble files on FAT/exFAT.
os.environ["COPYFILE_DISABLE"] = "1"


class ConversionError(Exception):
    """Raised when ffmpeg cannot produce a TM-2-compatible WAV."""


def ffmpeg_available(settings: Settings) -> bool:
    return shutil.which(settings.ffmpeg_binary) is not None


def convert_to_tm2_wav(
    source_path: Path,
    destination_path: Path,
    settings: Settings,
    logger: logging.Logger,
    channels_mode: str,
) -> dict:
    """
    Write a metadata-free PCM WAV that the TM-2 will accept.

    Roland Support notes that DAW tags in otherwise valid 16-bit/44.1 kHz files
    still produce a FORMAT error. ffmpeg bitexact output plus a RIFF sanitize
    pass strips those chunks.
    """
    if not ffmpeg_available(settings):
        raise ConversionError(
            f"{settings.ffmpeg_binary} is not on PATH. Install ffmpeg before converting samples."
        )

    channel_args = _channel_args(channels_mode)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    strip_card_metadata(destination_path.parent, logger)

    scratch = local_scratch_dir(destination_path)
    temp_path: Path | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="tm2_convert_", dir=scratch) as temp_dir:
            temp_path = Path(temp_dir)
            raw_wav = temp_path / "converted.wav"
            command = [
                settings.ffmpeg_binary,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(source_path),
                "-vn",
                "-ar",
                str(settings.sample_rate),
                *channel_args,
                "-c:a",
                "pcm_s16le",
                "-map_metadata",
                "-1",
                "-fflags",
                "+bitexact",
                "-flags:a",
                "+bitexact",
                str(raw_wav),
            ]
            logger.info("Converting %s with %s", source_path.name, " ".join(command))
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            if completed.returncode != 0:
                detail = completed.stderr.strip() or "ffmpeg failed with no stderr"
                logger.error("Conversion failed for %s: %s", source_path.name, detail)
                raise ConversionError(f"Could not convert {source_path.name}: {detail}")

            _write_clean_pcm_wav(raw_wav, destination_path)
            probe = inspect_wav(destination_path)
            if channels_mode == "auto" and probe["channels"] > 2:
                logger.info(
                    "Source %s has %s channels; downmixing to stereo for TM-2",
                    source_path.name,
                    probe["channels"],
                )
                return convert_to_tm2_wav(
                    destination_path,
                    destination_path,
                    settings,
                    logger,
                    "stereo",
                )
            strip_card_metadata(destination_path, logger)
            logger.info(
                "Wrote %s rate=%s depth=%s channels=%s duration=%.2fs",
                destination_path,
                probe["sample_rate"],
                probe["bit_depth"],
                probe["channels"],
                probe["duration_seconds"],
            )
            return probe
    finally:
        if temp_path is not None:
            remove_appledouble_sidecar(temp_path, logger)


def inspect_wav(path: Path) -> dict:
    """Read PCM WAV header fields without extra libraries."""
    with path.open("rb") as handle:
        header = handle.read(36)
        if len(header) < 36 or header[0:4] != b"RIFF" or header[8:12] != b"WAVE":
            raise ConversionError(f"{path.name} is not a WAVE file")

        audio_format, channels, sample_rate, _byte_rate, _block_align, bit_depth = struct.unpack(
            "<HHIIHH", header[20:36]
        )
        if audio_format != 1:
            raise ConversionError(f"{path.name} is not PCM WAV (format {audio_format})")

        data_size = _find_data_size(handle)
        bytes_per_frame = max(channels * (bit_depth // 8), 1)
        duration = data_size / float(sample_rate * bytes_per_frame)
        return {
            "sample_rate": sample_rate,
            "bit_depth": bit_depth,
            "channels": channels,
            "duration_seconds": round(duration, 3),
            "size_bytes": path.stat().st_size,
        }


def local_scratch_dir(avoid: Path | None = None) -> str:
    """Return a temp directory that is not on the same volume as the SD card."""
    avoid_dev = _device_id(avoid) if avoid is not None else None
    for candidate in (Path(tempfile.gettempdir()), Path("/tmp")):
        if not candidate.is_dir():
            continue
        if avoid_dev is None or _device_id(candidate) != avoid_dev:
            return str(candidate)
    return tempfile.gettempdir()


def remove_appledouble_sidecar(path: Path, logger: logging.Logger | None = None) -> None:
    """Delete the ._<name> file macOS leaves beside path. path itself may already be gone."""
    _unlink_quiet(path.with_name(f"._{path.name}"), logger)


def strip_card_metadata(path: Path, logger: logging.Logger | None = None) -> None:
    """Remove xattrs and AppleDouble files so FAT/exFAT writes do not keep ._* sidecars."""
    if path.exists():
        _strip_xattrs(path, logger)
    remove_appledouble_sidecar(path, logger)
    folder = path if path.is_dir() else path.parent
    if folder.is_dir():
        _purge_appledouble_files(folder, logger)


def _device_id(path: Path) -> int | None:
    current = path if path.exists() else path.parent
    try:
        return current.stat().st_dev
    except OSError:
        return None


def _strip_xattrs(path: Path, logger: logging.Logger | None) -> None:
    if not hasattr(os, "listxattr"):
        return
    try:
        names = os.listxattr(path)
    except OSError as exc:
        if logger:
            logger.info("Could not list xattrs for %s: %s", path, exc)
        return
    for name in names:
        try:
            os.removexattr(path, name)
        except OSError as exc:
            if logger:
                logger.info("Could not remove xattr %s from %s: %s", name, path, exc)


def _purge_appledouble_files(folder: Path, logger: logging.Logger | None) -> None:
    try:
        children = list(folder.iterdir())
    except OSError as exc:
        if logger:
            logger.info("Could not scan %s for AppleDouble files: %s", folder, exc)
        return
    for child in children:
        if child.is_file() and child.name.startswith("._"):
            _unlink_quiet(child, logger)


def _unlink_quiet(path: Path, logger: logging.Logger | None) -> None:
    try:
        if not path.is_file():
            return
        path.unlink()
    except OSError as exc:
        if logger:
            logger.info("Could not remove AppleDouble file %s: %s", path, exc)
        return
    if logger:
        logger.info("Removed AppleDouble file %s", path)


def _channel_args(channels_mode: str) -> list[str]:
    normalized = channels_mode.strip().lower()
    if normalized == "mono":
        return ["-ac", "1"]
    if normalized == "stereo":
        return ["-ac", "2"]
    return []


def _find_data_size(handle) -> int:
    while True:
        chunk_header = handle.read(8)
        if len(chunk_header) < 8:
            return 0
        chunk_id, chunk_size = struct.unpack("<4sI", chunk_header)
        if chunk_id == b"data":
            return chunk_size
        handle.seek(chunk_size, 1)


def _write_clean_pcm_wav(source_path: Path, destination_path: Path) -> None:
    """Keep only fmt and data chunks so leftover LIST/bext tags cannot trip the TM-2."""
    with source_path.open("rb") as handle:
        riff = handle.read(12)
        if len(riff) < 12 or riff[0:4] != b"RIFF" or riff[8:12] != b"WAVE":
            raise ConversionError("Converted output was not a WAVE file")

        fmt_chunk = b""
        data_chunk = b""
        while True:
            header = handle.read(8)
            if len(header) < 8:
                break
            chunk_id, chunk_size = struct.unpack("<4sI", header)
            payload = handle.read(chunk_size)
            if chunk_size % 2 == 1:
                handle.read(1)
            if chunk_id == b"fmt ":
                fmt_chunk = header + payload
            elif chunk_id == b"data":
                data_chunk = header + payload

    if not fmt_chunk or not data_chunk:
        raise ConversionError("Converted WAV was missing fmt or data chunks")

    body = fmt_chunk + data_chunk
    riff_size = 4 + len(body)
    destination_path.write_bytes(b"RIFF" + struct.pack("<I", riff_size) + b"WAVE" + body)
