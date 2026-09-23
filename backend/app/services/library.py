"""Search and download public sample libraries for TM-2 import."""

from __future__ import annotations

import json
import logging
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from app.config import Settings
from app.models import LibraryHit, LibraryPreset, LibrarySearchResponse, LibrarySourceInfo
from app.services.converter import (
    ConversionError,
    convert_to_tm2_wav,
    local_scratch_dir,
    remove_appledouble_sidecar,
)
from app.services.sdcard import (
    assert_folder_capacity,
    destination_folder,
    ensure_writable,
    unique_destination,
)


class LibraryError(Exception):
    """Public sample library failure."""


FOLDER_PRESETS: list[LibraryPreset] = [
    LibraryPreset(
        folder="Kicks",
        query="kick drum one-shot",
        duration_min=0.05,
        duration_max=4.0,
        description="Short kick / bass drum hits",
    ),
    LibraryPreset(
        folder="Snares",
        query="snare drum one-shot",
        duration_min=0.05,
        duration_max=4.0,
        description="Snare and rimshot hits",
    ),
    LibraryPreset(
        folder="Toms",
        query="tom drum one-shot",
        duration_min=0.05,
        duration_max=5.0,
        description="Tom hits",
    ),
    LibraryPreset(
        folder="Hats",
        query="hi-hat one-shot",
        duration_min=0.05,
        duration_max=4.0,
        description="Closed and open hats",
    ),
    LibraryPreset(
        folder="Cymbals",
        query="crash cymbal one-shot",
        duration_min=0.1,
        duration_max=8.0,
        description="Crash and ride hits",
    ),
    LibraryPreset(
        folder="Perc",
        query="percussion one-shot",
        duration_min=0.05,
        duration_max=5.0,
        description="Cowbell, clave, shaker, tamb",
    ),
    LibraryPreset(
        folder="FX",
        query="sound effect one-shot",
        duration_min=0.05,
        duration_max=8.0,
        description="FX and impacts",
    ),
    LibraryPreset(
        folder="Loops",
        query="drum loop",
        duration_min=8.0,
        duration_max=45.0,
        description="Short phrase loops",
    ),
    LibraryPreset(
        folder="Tracks",
        query="backing track percussion",
        duration_min=8.0,
        duration_max=45.0,
        description="Longer backing phrases",
    ),
]

_CC0_MARKERS = (
    "creative commons 0",
    "cc0",
    "publicdomain",
    "public domain",
    "zero/1.0",
)
_CC_BY_MARKERS = (
    "attribution",
    "cc by",
    "cc-by",
    "/by/3.0",
    "/by/4.0",
    "/by/2.0",
)
_NC_MARKERS = (
    "noncommercial",
    "non-commercial",
    "nc/",
    "by-nc",
)


def list_sources(settings: Settings) -> list[LibrarySourceInfo]:
    return [
        LibrarySourceInfo(
            id="catalog",
            label="Curated CC0 (VCSL)",
            configured=True,
            note="Local catalog of CC0 percussion WAVs. No API key. Safe for paid gigs.",
        ),
        LibrarySourceInfo(
            id="freesound",
            label="Freesound",
            configured=settings.freesound_configured,
            note=(
                "Search Freesound APIv2. Set FREESOUND_API_KEY in .env. "
                "v1 imports HQ previews and converts them to TM-2 WAV."
                if settings.freesound_configured
                else "Set FREESOUND_API_KEY from https://freesound.org/apiv2/apply"
            ),
        ),
        LibrarySourceInfo(
            id="archive",
            label="Internet Archive",
            configured=True,
            note="CC0 / public-domain / CC-BY audio only. Results can be messy.",
        ),
        LibrarySourceInfo(
            id="waves",
            label="Waves Local",
            configured=settings.waves_library_configured,
            note=(
                f"Installed samples in {settings.waves_library_dir}. "
                "Loose WAV, AIFF, FLAC, and MP3 files only."
                if settings.waves_library_configured
                else f"Folder not found: {settings.waves_library_dir}"
            ),
        ),
    ]


def search_library(
    settings: Settings,
    logger: logging.Logger,
    *,
    query: str,
    folder: str = "",
    source: str = "catalog",
    page: int = 1,
) -> LibrarySearchResponse:
    source_id = (source or "catalog").strip().lower()
    page = max(int(page or 1), 1)
    cleaned_query = (query or "").strip()
    preset = _preset_for_folder(folder) if folder else None
    use_preset_query = False
    if not cleaned_query and preset:
        cleaned_query = preset.query
        use_preset_query = True

    logger.info(
        "Library search source=%s query=%r folder=%s page=%s mode=%s",
        source_id,
        cleaned_query,
        folder,
        page,
        settings.library_license_mode,
    )

    if source_id == "catalog":
        # Folder chips fill a Freesound-oriented phrase; for the local catalog
        # only filter by folder unless the user typed a custom query.
        catalog_query = "" if use_preset_query else cleaned_query
        return _search_catalog(settings, catalog_query, folder, page)
    if source_id == "freesound":
        return _search_freesound(settings, logger, cleaned_query, folder, page, preset)
    if source_id == "archive":
        return _search_archive(settings, logger, cleaned_query, folder, page, preset)
    if source_id == "waves":
        waves_query = "" if use_preset_query else cleaned_query
        return _search_waves(settings, waves_query, folder, page)
    raise LibraryError(f"Unknown library source: {source_id}")


def import_library_sample(
    settings: Settings,
    logger: logging.Logger,
    *,
    card_path: str,
    folder: str,
    source: str,
    sample_id: str,
    channels: str = "",
    remount: bool = True,
) -> dict:
    hit = resolve_hit(settings, logger, source=source, sample_id=sample_id, folder=folder)
    target_folder_name = folder or hit.suggested_folder
    channel_mode = (channels or settings.default_channels).strip().lower()
    if channel_mode not in {"auto", "mono", "stereo"}:
        raise LibraryError("channels must be auto, mono, or stereo.")

    ensure_writable(card_path, logger, remount=remount)
    target_folder = destination_folder(card_path, target_folder_name, settings)
    assert_folder_capacity(target_folder, 1, settings)

    local_path = resolve_waves_file(settings, hit.id) if hit.source == "waves" else None
    download_url = hit.download_url or hit.preview_url
    if local_path is None and not download_url:
        raise LibraryError(f"No download URL for {hit.source}:{hit.id}")

    if local_path is not None:
        if local_path.name.startswith("."):
            raise LibraryError(f"Skipping hidden file {local_path.name}.")
        suffix = local_path.suffix.lower() or ".bin"
    else:
        suffix = Path(urllib.parse.urlparse(download_url).path).suffix.lower() or ".bin"
    if suffix not in settings.allowed_extension_set and suffix not in {".ogg", ".mp3", ".wav", ".flac", ".aiff", ".aif"}:
        suffix = ".bin"

    with tempfile.NamedTemporaryFile(
        prefix="tm2_lib_",
        suffix=suffix,
        dir=local_scratch_dir(target_folder),
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)

    try:
        if local_path is not None:
            shutil.copyfile(local_path, temp_path)
        else:
            _download_file(download_url, temp_path, settings, logger)
        destination = unique_destination(target_folder, hit.name, settings)
        probe = convert_to_tm2_wav(
            source_path=temp_path,
            destination_path=destination,
            settings=settings,
            logger=logger,
            channels_mode=channel_mode,
        )
    except (ConversionError, OSError, urllib.error.URLError) as exc:
        raise LibraryError(f"Could not import {hit.name}: {exc}") from exc
    finally:
        temp_path.unlink(missing_ok=True)
        remove_appledouble_sidecar(temp_path, logger)

    logger.info(
        "Imported library sample source=%s id=%s license=%s path=%s",
        hit.source,
        hit.id,
        hit.license,
        destination,
    )
    note = "Wrote TM-2 PCM WAV with metadata removed."
    if hit.download_kind == "preview":
        note = "Converted Freesound HQ preview to TM-2 PCM WAV (original download needs OAuth)."

    return {
        "original_name": hit.name,
        "saved_name": destination.name,
        "folder": target_folder.name if target_folder.name != settings.wave_parts[-1] else "",
        "path": str(destination),
        "converted": True,
        "sample_rate": probe["sample_rate"],
        "bit_depth": probe["bit_depth"],
        "channels": probe["channels"],
        "duration_seconds": probe["duration_seconds"],
        "message": note,
        "license": hit.license,
        "license_url": hit.license_url,
        "author": hit.author,
        "source": hit.source,
        "id": hit.id,
        "commercial_ok": hit.commercial_ok,
    }


def resolve_hit(
    settings: Settings,
    logger: logging.Logger,
    *,
    source: str,
    sample_id: str,
    folder: str = "",
) -> LibraryHit:
    source_id = source.strip().lower()
    if source_id == "catalog":
        for hit in _catalog_hits(settings):
            if hit.id == sample_id:
                return hit
        raise LibraryError(f"Catalog sample {sample_id} was not found.")
    if source_id == "freesound":
        return _freesound_sound(settings, logger, sample_id, folder)
    if source_id == "archive":
        return _archive_sound(settings, logger, sample_id, folder)
    if source_id == "waves":
        return _waves_hit_for_id(settings, sample_id)
    raise LibraryError(f"Unknown library source: {source_id}")


def _preset_for_folder(folder: str) -> LibraryPreset | None:
    for preset in FOLDER_PRESETS:
        if preset.folder.lower() == folder.strip().lower():
            return preset
    return None


def _search_catalog(
    settings: Settings,
    query: str,
    folder: str,
    page: int,
) -> LibrarySearchResponse:
    hits = _catalog_hits(settings)
    if folder:
        hits = [hit for hit in hits if hit.suggested_folder.lower() == folder.lower()]
    if query:
        needle = query.lower()
        hits = [
            hit
            for hit in hits
            if needle in hit.name.lower()
            or needle in " ".join(hit.tags).lower()
            or needle in hit.suggested_folder.lower()
        ]
    page_size = settings.library_page_size
    start = (page - 1) * page_size
    page_hits = hits[start : start + page_size]
    return LibrarySearchResponse(
        source="catalog",
        query=query,
        page=page,
        page_size=page_size,
        count=len(hits),
        hits=page_hits,
    )


def _catalog_hits(settings: Settings) -> list[LibraryHit]:
    path = settings.catalog_path
    if not path.exists():
        raise LibraryError(f"Catalog missing at {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    base = payload.get("base_url", "").rstrip("/") + "/"
    license_name = payload.get("license", "CC0-1.0")
    license_url = payload.get("license_url", "")
    author = payload.get("author", "VCSL")
    hits: list[LibraryHit] = []
    for item in payload.get("samples", []):
        file_path = item["path"].lstrip("/")
        url = urllib.parse.urljoin(base, urllib.parse.quote(file_path))
        hits.append(
            LibraryHit(
                id=item["id"],
                source="catalog",
                name=item["name"],
                license=license_name,
                license_url=license_url,
                author=author,
                duration_seconds=None,
                preview_url=url,
                download_url=url,
                download_kind="direct",
                suggested_folder=item.get("suggested_folder", "Perc"),
                commercial_ok=True,
                tags=list(item.get("tags", [])),
                note="Original CC0 WAV from VCSL.",
            )
        )
    return hits


_WAVES_CACHE: dict[str, tuple[float, float, list[LibraryHit]]] = {}
_WAVES_CACHE_SECONDS = 60.0
_WAVES_ID_PREFIX = "waves-"


def resolve_waves_file(settings: Settings, sample_id: str) -> Path:
    """Return a playable file under the configured Waves library. Rejects paths outside it."""
    root = _waves_root(settings)
    token = sample_id[len(_WAVES_ID_PREFIX) :] if sample_id.startswith(_WAVES_ID_PREFIX) else sample_id
    relative = Path(urllib.parse.unquote(token))
    if relative.is_absolute() or ".." in relative.parts:
        raise LibraryError("Invalid Waves sample id.")
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise LibraryError(f"Waves sample was not found: {relative.as_posix()}")
    if target.suffix.lower() not in settings.allowed_extension_set:
        raise LibraryError(f"{target.name} is not a supported audio file.")
    return target


def _search_waves(
    settings: Settings,
    query: str,
    folder: str,
    page: int,
) -> LibrarySearchResponse:
    hits = _waves_hits(settings)
    if folder:
        hits = [hit for hit in hits if hit.suggested_folder.lower() == folder.lower()]
    if query:
        needles = [part for part in query.lower().split() if part]
        hits = [
            hit
            for hit in hits
            if all(
                needle in hit.name.lower()
                or needle in " ".join(hit.tags).lower()
                or needle in hit.note.lower()
                for needle in needles
            )
        ]
    page_size = settings.library_page_size
    start = (page - 1) * page_size
    return LibrarySearchResponse(
        source="waves",
        query=query,
        page=page,
        page_size=page_size,
        count=len(hits),
        hits=hits[start : start + page_size],
        warnings=[
            "Local Waves install. Encrypted instrument files are skipped.",
        ],
    )


def _waves_hit_for_id(settings: Settings, sample_id: str) -> LibraryHit:
    for hit in _waves_hits(settings):
        if hit.id == sample_id:
            return hit
    raise LibraryError(f"Waves sample {sample_id} was not found.")


def _waves_root(settings: Settings) -> Path:
    root = settings.waves_library_dir
    if not root.is_dir():
        raise LibraryError(
            f"Waves library folder was not found at {root}. Set WAVES_LIBRARY_PATH in .env."
        )
    return root.resolve()


def _waves_hits(settings: Settings) -> list[LibraryHit]:
    root = _waves_root(settings)
    key = str(root)
    now = time.monotonic()
    stamp = root.stat().st_mtime
    cached = _WAVES_CACHE.get(key)
    if cached and cached[1] == stamp and now - cached[0] < _WAVES_CACHE_SECONDS:
        return cached[2]

    hits: list[LibraryHit] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.name.startswith("."):
            continue
        if path.suffix.lower() not in settings.allowed_extension_set:
            continue
        relative = path.relative_to(root)
        sample_id = _WAVES_ID_PREFIX + urllib.parse.quote(relative.as_posix(), safe="")
        pack = relative.parts[0] if len(relative.parts) > 1 else root.name
        hits.append(
            LibraryHit(
                id=sample_id,
                source="waves",
                name=path.stem,
                license="Local",
                license_url="",
                author="Waves",
                duration_seconds=None,
                preview_url=f"/api/library/audio?source=waves&id={urllib.parse.quote(sample_id, safe='')}",
                download_url=str(path),
                download_kind="local",
                suggested_folder=_guess_folder(path.stem, list(relative.parts[:-1])),
                commercial_ok=True,
                tags=[part.replace(" SD", "") for part in relative.parts[:-1]],
                note=pack,
            )
        )
    hits.sort(key=lambda hit: (hit.suggested_folder, hit.name.lower()))
    _WAVES_CACHE[key] = (now, stamp, hits)
    return hits


def _search_freesound(
    settings: Settings,
    logger: logging.Logger,
    query: str,
    folder: str,
    page: int,
    preset: LibraryPreset | None,
) -> LibrarySearchResponse:
    if not settings.freesound_configured:
        raise LibraryError("Freesound is not configured. Set FREESOUND_API_KEY in .env.")

    if not query:
        raise LibraryError("Enter a search query or pick a folder preset.")

    duration_min = preset.duration_min if preset else 0.05
    duration_max = preset.duration_max if preset else 8.0
    filters = [
        "type:(wav OR aiff OR flac OR ogg OR mp3)",
        f"duration:[{duration_min} TO {duration_max}]",
    ]
    if settings.library_license_mode == "performance":
        filters.append(
            "license:("
            '"http://creativecommons.org/publicdomain/zero/1.0/" OR '
            '"http://creativecommons.org/licenses/by/4.0/" OR '
            '"http://creativecommons.org/licenses/by/3.0/" OR '
            '"http://creativecommons.org/licenses/by/2.5/" OR '
            '"http://creativecommons.org/licenses/by/2.0/"'
            ")"
        )
    params = {
        "query": query,
        "filter": " ".join(filters),
        "fields": "id,name,tags,username,license,duration,previews,type,samplerate,filesize,download",
        "page": str(page),
        "page_size": str(settings.library_page_size),
        "token": settings.freesound_api_key.strip(),
    }
    url = settings.freesound_search_url.rstrip("/") + "/?" + urllib.parse.urlencode(params)
    payload = _http_json(url, settings, logger)
    hits: list[LibraryHit] = []
    warnings: list[str] = []
    for item in payload.get("results", []):
        hit = _normalize_freesound(item, folder)
        if not _license_allowed(hit.license, hit.license_url, settings.library_license_mode):
            continue
        hits.append(hit)

    if settings.library_license_mode == "performance":
        warnings.append("Showing CC0 and CC-BY only. Toggle license mode to any for NC results.")

    return LibrarySearchResponse(
        source="freesound",
        query=query,
        page=page,
        page_size=settings.library_page_size,
        count=int(payload.get("count", len(hits))),
        hits=hits,
        warnings=warnings,
    )


def _freesound_sound(
    settings: Settings,
    logger: logging.Logger,
    sample_id: str,
    folder: str,
) -> LibraryHit:
    if not settings.freesound_configured:
        raise LibraryError("Freesound is not configured. Set FREESOUND_API_KEY in .env.")
    sound_id = sample_id.replace("freesound-", "")
    params = {
        "fields": "id,name,tags,username,license,duration,previews,type,samplerate,filesize,download",
        "token": settings.freesound_api_key.strip(),
    }
    base = settings.freesound_sound_url.rstrip("/") + f"/{sound_id}/"
    url = base + "?" + urllib.parse.urlencode(params)
    item = _http_json(url, settings, logger)
    hit = _normalize_freesound(item, folder)
    if not _license_allowed(hit.license, hit.license_url, settings.library_license_mode):
        raise LibraryError(f"{hit.name} is blocked by LIBRARY_LICENSE_MODE={settings.library_license_mode}.")
    return hit


def _normalize_freesound(item: dict, folder: str) -> LibraryHit:
    previews = item.get("previews") or {}
    preview_url = (
        previews.get("preview-hq-ogg")
        or previews.get("preview-hq-mp3")
        or previews.get("preview-lq-ogg")
        or previews.get("preview-lq-mp3")
        or ""
    )
    license_name = str(item.get("license") or "Unknown")
    commercial_ok = _is_commercial_ok(license_name, license_name)
    suggested = folder or _guess_folder(item.get("name", ""), item.get("tags") or [])
    return LibraryHit(
        id=f"freesound-{item['id']}",
        source="freesound",
        name=str(item.get("name") or f"sound-{item['id']}"),
        license=license_name,
        license_url=license_name if license_name.startswith("http") else "",
        author=str(item.get("username") or "freesound"),
        duration_seconds=float(item["duration"]) if item.get("duration") is not None else None,
        preview_url=preview_url,
        download_url=preview_url,
        download_kind="preview",
        suggested_folder=suggested,
        commercial_ok=commercial_ok,
        tags=[str(tag) for tag in (item.get("tags") or [])],
        note="Import converts the Freesound HQ preview. Original WAV download requires OAuth2.",
    )


def _search_archive(
    settings: Settings,
    logger: logging.Logger,
    query: str,
    folder: str,
    page: int,
    preset: LibraryPreset | None,
) -> LibrarySearchResponse:
    if not query:
        raise LibraryError("Enter a search query or pick a folder preset.")

    if settings.library_license_mode == "any":
        license_clause = "licenseurl:*creativecommons*"
    else:
        # Path wildcards such as licenses/by/4.0* make Archive.org's search
        # return an Elasticsearch error. Exclude NC here and keep the
        # stricter CC0 / CC-BY check in _license_allowed.
        license_clause = "licenseurl:*creativecommons* AND -licenseurl:*by-nc*"

    q = f"mediatype:audio AND ({license_clause}) AND ({_archive_text_query(query)})"
    rows = settings.library_page_size
    params = [
        ("q", q),
        ("fl[]", "identifier"),
        ("fl[]", "title"),
        ("fl[]", "creator"),
        ("fl[]", "licenseurl"),
        ("rows", str(rows)),
        ("page", str(page)),
        ("output", "json"),
    ]
    # advancedsearch.php is a script. A slash before the query string 404s.
    base = settings.archive_search_url.split("?", 1)[0].rstrip("/")
    url = base + "?" + urllib.parse.urlencode(params)
    payload = _http_json(url, settings, logger)
    if payload.get("error"):
        raise LibraryError("Internet Archive search failed. Try a shorter query.")
    response = payload.get("response") or {}
    docs = response.get("docs") or []
    hits: list[LibraryHit] = []
    warnings = [
        "Archive.org results vary. Prefer catalog or Freesound for drum one-shots.",
    ]
    for doc in docs:
        identifier = str(doc.get("identifier") or "")
        if not identifier:
            continue
        license_url = str(doc.get("licenseurl") or "")
        if isinstance(doc.get("licenseurl"), list):
            license_url = str(doc["licenseurl"][0]) if doc["licenseurl"] else ""
        license_name = _license_label_from_url(license_url)
        if not _license_allowed(license_name, license_url, settings.library_license_mode):
            continue
        creator = doc.get("creator") or "Internet Archive"
        if isinstance(creator, list):
            creator = creator[0] if creator else "Internet Archive"
        title = doc.get("title") or identifier
        if isinstance(title, list):
            title = title[0]
        suggested = folder or (preset.folder if preset else _guess_folder(str(title), []))
        hits.append(
            LibraryHit(
                id=f"archive-{identifier}",
                source="archive",
                name=str(title)[:80],
                license=license_name,
                license_url=license_url,
                author=str(creator),
                duration_seconds=None,
                preview_url="",
                download_url="",
                download_kind="direct",
                suggested_folder=suggested,
                commercial_ok=_is_commercial_ok(license_name, license_url),
                tags=[],
                note="Import resolves the first WAV/MP3/FLAC/OGG file on the item.",
            )
        )
    return LibrarySearchResponse(
        source="archive",
        query=query,
        page=page,
        page_size=rows,
        count=int(response.get("numFound", len(hits))),
        hits=hits,
        warnings=warnings,
    )


def _archive_sound(
    settings: Settings,
    logger: logging.Logger,
    sample_id: str,
    folder: str,
) -> LibraryHit:
    identifier = sample_id.replace("archive-", "", 1)
    meta_url = settings.archive_metadata_url.rstrip("/") + "/" + urllib.parse.quote(identifier)
    payload = _http_json(meta_url, settings, logger)
    metadata = payload.get("metadata") or {}
    files = payload.get("files") or []
    audio = None
    for item in files:
        name = str(item.get("name") or "")
        lower = name.lower()
        if lower.endswith((".wav", ".flac", ".aiff", ".aif", ".ogg", ".mp3")):
            audio = item
            if lower.endswith(".wav"):
                break
    if not audio:
        raise LibraryError(f"No downloadable audio file on Archive.org item {identifier}.")

    filename = str(audio["name"])
    download_url = (
        settings.archive_download_url.rstrip("/")
        + "/"
        + urllib.parse.quote(identifier)
        + "/"
        + urllib.parse.quote(filename)
    )
    license_url = str(metadata.get("licenseurl") or "")
    if isinstance(metadata.get("licenseurl"), list):
        license_url = metadata["licenseurl"][0] if metadata["licenseurl"] else ""
    license_name = _license_label_from_url(license_url)
    if not _license_allowed(license_name, license_url, settings.library_license_mode):
        raise LibraryError(f"{identifier} is blocked by LIBRARY_LICENSE_MODE={settings.library_license_mode}.")
    creator = metadata.get("creator") or "Internet Archive"
    if isinstance(creator, list):
        creator = creator[0] if creator else "Internet Archive"
    title = metadata.get("title") or filename
    if isinstance(title, list):
        title = title[0]
    return LibraryHit(
        id=f"archive-{identifier}",
        source="archive",
        name=str(title)[:80],
        license=license_name,
        license_url=license_url,
        author=str(creator),
        duration_seconds=None,
        preview_url=download_url,
        download_url=download_url,
        download_kind="direct",
        suggested_folder=folder or _guess_folder(str(title), []),
        commercial_ok=_is_commercial_ok(license_name, license_url),
        tags=[],
        note=f"Downloading {filename}",
    )


def _guess_folder(name: str, tags: list) -> str:
    blob = f"{name} {' '.join(str(t) for t in tags)}".lower()
    mapping = [
        ("Kicks", ("kick", "bassdrum", "bass drum", "bd ")),
        ("Snares", ("snare", "rimshot", "clap")),
        ("Toms", ("tom",)),
        ("Hats", ("hihat", "hi-hat", "hi hat", "hh ")),
        ("Cymbals", ("crash", "ride", "cymbal")),
        ("Loops", ("loop", "groove")),
        ("Tracks", ("backing", "track", "song")),
        ("FX", ("fx", "effect", "impact", "riser", "gong")),
        ("Perc", ("perc", "cowbell", "shaker", "tamb", "clave", "conga", "bongo")),
    ]
    for folder, needles in mapping:
        if any(needle in blob for needle in needles):
            return folder
    return "Perc"


def _archive_text_query(query: str) -> str:
    """Turn a user phrase into Archive.org search terms.

    A hyphen is the NOT operator, so "one-shot" would exclude "shot".
    Archive.org also has almost no items titled with that qualifier, so drop it.
    """
    cleaned = query.replace('"', " ").replace("-", " ")
    cleaned = re.sub(r"\bone\s+shot\b", " ", cleaned, flags=re.IGNORECASE)
    terms = cleaned.split()
    if not terms:
        return "audio"
    if len(terms) == 1:
        return terms[0]
    if len(terms) <= 3:
        return '"' + " ".join(terms) + '"'
    return " ".join(terms)


def _license_allowed(license_name: str, license_url: str, mode: str) -> bool:
    if mode == "any":
        return True
    return _is_commercial_ok(license_name, license_url)


def _is_commercial_ok(license_name: str, license_url: str) -> bool:
    blob = f"{license_name} {license_url}".lower()
    if any(marker in blob for marker in _NC_MARKERS):
        return False
    if any(marker in blob for marker in _CC0_MARKERS):
        return True
    if any(marker in blob for marker in _CC_BY_MARKERS) and "nc" not in blob:
        return True
    # Freesound often returns the full license URL string as license
    if "creativecommons.org/publicdomain" in blob:
        return True
    if re.search(r"creativecommons\.org/licenses/by/\d", blob) and "nc" not in blob:
        return True
    return False


def _license_label_from_url(license_url: str) -> str:
    lower = (license_url or "").lower()
    if "zero" in lower or "publicdomain" in lower:
        return "CC0"
    if "by-nc" in lower:
        return "CC-BY-NC"
    if "/by/" in lower:
        return "CC-BY"
    return license_url or "Unknown"


def _http_json(url: str, settings: Settings, logger: logging.Logger) -> dict:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": settings.library_user_agent, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        logger.info("Library HTTP %s for %s: %s", exc.code, url, detail)
        raise LibraryError(f"Upstream returned HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise LibraryError(f"Could not reach library host: {exc.reason}") from exc
    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise LibraryError("Upstream returned invalid JSON.") from exc


def _download_file(url: str, destination: Path, settings: Settings, logger: logging.Logger) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": settings.library_user_agent},
        method="GET",
    )
    logger.info("Downloading library file %s", url)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            total = 0
            with destination.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > settings.max_upload_bytes:
                        raise LibraryError(
                            f"Download exceeds {settings.max_upload_mb} MB upload limit."
                        )
                    handle.write(chunk)
    except urllib.error.HTTPError as exc:
        raise LibraryError(f"Download failed with HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise LibraryError(f"Download failed: {exc.reason}") from exc
