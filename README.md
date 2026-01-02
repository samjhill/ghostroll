## GhostRoll

![GhostRoll device](images/header.png)

GhostRoll is a “drop the SD card in and it just works” ingest pipeline:

**SD card → local session → share-friendly JPEGs + thumbnails + gallery → private S3 → one share link**

It’s designed to be:

- **Low-friction** (watch mode + one URL)
- **Incremental** (dedupe so re-inserting the same card is fast)
- **Privacy-friendly** (derived images strip metadata; S3 stays private)

## Quick start (macOS)

### 1) Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

### 2) Configure AWS (once)

GhostRoll uses the AWS CLI (`aws s3 cp` + `aws s3 presign`), so make sure this works:

```bash
aws configure
aws sts get-caller-identity
```

If you prefer to edit files directly, use the templates in:

- `docs/aws/credentials.example`
- `docs/aws/config.example`
- `docs/aws/iam-policy-ghostroll-s3.json` (starter least-privilege policy)

### 3) Name your SD card

Set the SD card volume label to:

- `auto-import`

macOS sometimes mounts as `auto-import 1`, etc — GhostRoll handles that.

### 4) Run watch mode

```bash
ghostroll watch
```

When it finishes, you’ll get a session directory under `~/ghostroll/` with a `share.txt` presigned URL.

## Troubleshooting: doctor

If something feels misconfigured (AWS creds, bucket perms, mount roots, disk space), run:

```bash
ghostroll doctor
```

## Continuous reliability

This repo includes:

- `ghostroll doctor` for quick environment checks
- a small CI smoke test (`tests/test_pipeline_smoke.py`) that runs on every push via GitHub Actions

## License

This project is licensed under the **PolyForm Noncommercial License 1.0.0** (non‑commercial use only). See `LICENSE`.

## What you get (per session)

Default location:

- `~/ghostroll/<SESSION_ID>/`

Contents:

- `originals/` (copied from the card; preserves structure)
- `derived/share/` (max 2048px long edge, quality ~90, auto-oriented, metadata stripped)
- `derived/thumbs/` (max 512px long edge, quality ~85, auto-oriented, metadata stripped)
- `index.html` (local gallery)
- `share.txt` (the link you share)
- `share-qr.png` (QR for the share link)
- `ghostroll.log` (session log)

The uploaded `index.html` is generated to work with a **private** bucket: it embeds presigned URLs for the images.
The gallery includes a responsive grid and a lightbox (click to open, Esc to close, ←/→ to navigate).
It also includes a **Download all** link for the session’s share images.

## Dedupe / incremental behavior

GhostRoll keeps a persistent SQLite DB keyed by **SHA-256 of file bytes** (default `~/.ghostroll/ghostroll.db`).

- Re-insert same card with no new photos: it will quickly report “No new files detected”.
- Add new photos: only the new files are copied/processed/uploaded.

## Configuration

You can configure via env vars (CLI flags override env):

- `GHOSTROLL_SD_LABEL` (default `auto-import`)
- `GHOSTROLL_BASE_DIR` (default `~/ghostroll`)
- `GHOSTROLL_DB_PATH` (default `~/.ghostroll/ghostroll.db`)
- `GHOSTROLL_S3_BUCKET` (default `photo-ingest-project`)
- `GHOSTROLL_S3_PREFIX_ROOT` (default `sessions/`)
- `GHOSTROLL_PRESIGN_EXPIRY_SECONDS` (default `604800`)
- `GHOSTROLL_MOUNT_ROOTS` (default `/Volumes,/media,/run/media,/mnt`)
- `GHOSTROLL_STATUS_PATH` (default `~/ghostroll/status.json`)
- `GHOSTROLL_STATUS_IMAGE_PATH` (default `~/ghostroll/status.png`)
- `GHOSTROLL_STATUS_IMAGE_SIZE` (default `800x480`)
- `GHOSTROLL_PROCESS_WORKERS` (default: CPU-count clamped to 1–6)
- `GHOSTROLL_UPLOAD_WORKERS` (default `4`)
- `GHOSTROLL_PRESIGN_WORKERS` (default `8`)

Image settings:

- `GHOSTROLL_SHARE_MAX_LONG_EDGE` (default `2048`)
- `GHOSTROLL_SHARE_QUALITY` (default `90`)
- `GHOSTROLL_THUMB_MAX_LONG_EDGE` (default `512`)
- `GHOSTROLL_THUMB_QUALITY` (default `85`)

## Raspberry Pi / e‑ink

GhostRoll runs on Linux and writes status outputs that work well for e‑ink:

- `status.json` (machine-readable)
- `status.png` (monochrome “now doing X” image)

If you want a “flash once, boot, and it runs” image with systemd + boot-partition config, follow:

- `pi/README.md`

## Legacy shell prototype

The original prototype is still in `ingest.sh` (rsync + ImageMagick + rclone + aws presign).


