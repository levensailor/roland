# Roland TM-2 Sample Loader

A local full-stack tool that converts audio to Roland TM-2-legal WAV files and writes them to a mounted SD card in the official `Roland/TM-2/WAVE` folder tree.

The TM-2 only plays 44.1 kHz, 16-bit, mono or stereo PCM WAV files. DAW metadata can still trigger a `FORMAT` error. This app converts dropped files (WAV, MP3, AIFF, FLAC, M4A, OGG, and similar), strips tags, and keeps one folder level under `WAVE` so the module can see the sounds.

## Author

levensailor

## Public assets and references

- App UI: `http://localhost:8080` after you start the backend on the machine that has the SD card mounted
- [Roland TM-2 product page](https://www.roland.com/us/products/tm-2/)
- [TM-2 owner's manual (PDF)](https://static.roland.com/assets/media/pdf/TM-2_eng04_W.pdf)
- [Roland support: notes on playing WAV files from an SD card](https://support.roland.com/hc/en-us/articles/201920029-TM-2-Notes-Regarding-Playing-Audio-WAV-Files-from-an-SD-Card)

## Login

There is no login. The app is meant to run on the computer attached to the SD card reader. Do not expose it to the public internet.

## What it writes

```text
<SD card root>/
  Roland/
    TM-2/
      WAVE/
        Kicks/
        Snares/
        Toms/
        Hats/
        Cymbals/
        Perc/
        FX/
        Loops/
        Tracks/
```

That layout matches the manual: files go in `Roland/TM-2/WAVE`, with at most one folder level underneath, 300 folders max, and 300 files per folder. Names are forced to ASCII.

## Prerequisites

- Python 3.10 or newer, including 3.14. The pinned FastAPI/Pydantic releases ship 3.14 wheels so you do not have to compile `pydantic-core`.
- [ffmpeg](https://ffmpeg.org/) on your `PATH` (used for conversion)
- An SD or SDHC card, 32 GB or smaller, formatted on the TM-2 the first time you use it

macOS ffmpeg install:

```bash
brew install ffmpeg
```

## Run the app

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env
```

Optional: set `SDCARD_PATH` in `.env` to the mounted card, for example `/Volumes/NO NAME`.

Start the API and the brutalist web UI. Host and port come from `.env` (`HOST`, `PORT`):

```bash
cd backend
python -m app.main
```

Equivalent uvicorn command:

```bash
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Open [http://localhost:8080](http://localhost:8080).

1. Insert the SD card into this computer with the TM-2 powered off.
2. Select the volume or paste its path.
3. Click **Init WAVE tree**. If the badge says READ-ONLY, macOS mounted a dirty FAT (usually from pulling the card while the TM-2 was on). Use **Remount RW**, or eject and reinsert. The lock switch is a different problem (`Media Read-Only`).
4. Drag audio onto a folder tile, or use **04 / Public library** to search curated CC0 packs, Freesound, Internet Archive, or Waves Local and write them to the card.
5. Eject the card, insert it with the TM-2 off, then assign files on the module with `INST` and `SHIFT` + `-` / `+` to reach the SD list.

`GET /api/routes` lists every API path. All card write routes accept `{ "card_path": "/Volumes/TM-2", ... }` as JSON except upload, which is multipart form fields `card_path`, `folder`, `channels`, and `files`.

Library routes:

- `GET /api/library/sources` — configured backends and folder presets
- `GET /api/library/search?q=&folder=&source=catalog|freesound|archive|waves&page=` — search hits with license badges
- `GET /api/library/audio?source=waves&id=` — stream a file from the local Waves library
- `POST /api/library/import` — `{ "card_path", "folder", "source", "id", "channels", "remount" }` downloads or copies, converts, and writes WAVE

The right-hand **READ THIS EVERY TIME** panel repeats the pad-assignment steps. The TM-2 does not copy samples into internal memory. The card must stay inserted or the display shows `NO CARD`.

## Public sample library

Panel **04 / Public library** searches live-performance-oriented sources and imports through the same converter as drag-and-drop.

| Source | Key required | Notes |
| --- | --- | --- |
| Catalog (VCSL) | No | Curated CC0 percussion WAVs from [sgossner/VCSL](https://github.com/sgossner/VCSL/). Safe for paid gigs. |
| Freesound | Yes | Apply at [freesound.org/apiv2/apply](https://freesound.org/apiv2/apply). Set `FREESOUND_API_KEY` in `.env`. v1 imports HQ previews and converts them to TM-2 WAV (original download needs OAuth2). |
| Internet Archive | No | Filtered to public-domain / CC0 / CC-BY. Results vary; prefer Catalog or Freesound for drum one-shots. |
| Waves Local | No | Installed samples under `WAVES_LIBRARY_PATH`. Lists loose WAV, AIFF, FLAC, and MP3 files. Encrypted Waves instrument blobs are skipped. |

`LIBRARY_LICENSE_MODE=performance` (default) keeps CC0 and CC-BY only and hides NC licenses that are unsafe for paid gigs. Set `LIBRARY_LICENSE_MODE=any` to include non-commercial results (shown with an NC warning).

BBC Sound Effects and Pixabay audio are intentionally not integrated (non-commercial RemArc terms, or no public audio API).

## Configuration

Copy `.env.example` to `.env`. All names, ports, folder labels, sample-rate limits, library URLs, and log paths come from those variables. Logs write to the console and to a rotating file (`1 MB`, 3 backups) with an America/New_York timestamp, function name, and line number.

Relevant library variables:

```bash
FREESOUND_API_KEY=
FREESOUND_SEARCH_URL=https://freesound.org/apiv2/search/
LIBRARY_LICENSE_MODE=performance
LIBRARY_USER_AGENT=Roland-TM-2-Sample-Loader/1.0
LIBRARY_PAGE_SIZE=24
WAVES_LIBRARY_PATH=/Applications/Waves/Data/Instrument Data/Waves Sample Libraries
```

## Deployment

Run this on the workstation that mounts the SD card. A remote host cannot see a card plugged into your desk.

If you still want a small always-on box on the same bench as the card reader, a free-tier EC2 instance with a public IP, a security group that opens SSH and HTTPS, and the steps above is enough. Harden later. Point the instance at a locally attached reader; do not expect a cloud VM to write a card that is in your laptop.

## Project layout

- `backend/` — FastAPI, conversion, SD card writes, public library search
- `backend/app/library/catalog.json` — curated CC0 VCSL one-shot index (URLs only, no WAV binaries)
- `frontend/` — drag-and-drop UI, public library panel, and TM-2 reminders
- `CHANGELOG.md` — dated feature list
- `CONTRIBUTING.md` — feature-branch and pull-request process
