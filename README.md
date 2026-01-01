# GhostRoll

GhostRoll is a local ingest pipeline:

**SD Card (DCIM) → local session folder → share-friendly JPEGs + thumbs + gallery → private S3 → one presigned URL**

## Prerequisites

- **macOS** (watch mode uses `/Volumes`; Raspberry Pi/Linux notes below)
- **Python 3.10+**
- **AWS CLI** installed and configured (`aws sts get-caller-identity` succeeds)
- An existing private S3 bucket (default: `photo-ingest-project`)

Optional:

- `rclone` (not required by the current Python implementation; your original `ingest.sh` uses it)

## Setup

Create a venv and install:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

## SD card naming

Rename your SD card volume label to:

- `auto-import`

GhostRoll also handles macOS suffixes like `auto-import 1`, `auto-import 2`, etc.

## Usage

### Watch mode (recommended)

Runs once per card insert, then waits for removal before running again:

```bash
ghostroll watch
```

### One-shot run (debugging)

```bash
ghostroll run --volume /Volumes/auto-import
```

## Outputs

By default sessions are written under:

- `~/ghostroll/<SESSION_ID>/`

Each session contains:

- `originals/` (copied from SD, preserving structure)
- `derived/share/` (max 2048px long edge, quality ~90, auto-oriented, metadata stripped)
- `derived/thumbs/` (max 512px long edge, quality ~85, auto-oriented, metadata stripped)
- `index.html` (simple static gallery)
- `share.txt` (presigned URL)
- `share-qr.png` (QR code for the presigned URL)
- `ghostroll.log` (session log)

Note: the uploaded gallery page is generated to work with a **private** S3 bucket. It embeds **presigned URLs for each image**, so you can share a single presigned link to the gallery page and the images still load.

## Configuration

Configure via env vars (CLI flags override env):

- `GHOSTROLL_SD_LABEL` (default `auto-import`)
- `GHOSTROLL_BASE_DIR` (default `~/ghostroll`)
- `GHOSTROLL_DB_PATH` (default `~/.ghostroll/ghostroll.db`)
- `GHOSTROLL_S3_BUCKET` (default `photo-ingest-project`)
- `GHOSTROLL_S3_PREFIX_ROOT` (default `sessions/`)
- `GHOSTROLL_PRESIGN_EXPIRY_SECONDS` (default `604800`)
- `GHOSTROLL_SHARE_MAX_LONG_EDGE` (default `2048`)
- `GHOSTROLL_SHARE_QUALITY` (default `90`)
- `GHOSTROLL_THUMB_MAX_LONG_EDGE` (default `512`)
- `GHOSTROLL_THUMB_QUALITY` (default `85`)
- `GHOSTROLL_POLL_SECONDS` (default `2`)

## Dedupe / incremental behavior

GhostRoll maintains a persistent SQLite DB (default `~/.ghostroll/ghostroll.db`) keyed by **SHA-256 of file bytes**.

- Re-inserting the same card with no new photos: **no new session is created** by default (it logs “No new files detected”).
- Adding new photos: only those new files are copied/processed/uploaded.

If you want a session even when nothing is new, use:

```bash
ghostroll watch --always-create-session
```

## Acceptance test checklist

- **A1**: Insert card with `DCIM/` + JPEGs → session created → derived files exist → uploads succeed → `share.txt` URL loads gallery.
- **A2**: Reinsert without new photos → “No new files detected; nothing to do.” (fast).
- **A3**: Add a few new photos → only those are processed/uploaded.
- **A4**: RAW+JPEG → RAW is ingested into `originals/`; derivatives are generated from the JPEG (fast).

## Raspberry Pi / Linux notes (future)

The pipeline core is OS-agnostic; only **device detection** changes.

On Linux/Raspberry Pi you’d likely:

- Replace `/Volumes` polling with:
  - a systemd unit + udev rule, or
  - polling `/media/<user>/...` or `/run/media/...`
- Keep the `ghostroll run --volume ...` core intact.

## Legacy shell prototype

The original prototype is still in `ingest.sh` (uses `rsync` + `magick` + `rclone` + `aws s3 presign`).


