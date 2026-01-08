from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
import multiprocessing


def _expand(p: str) -> Path:
    return Path(os.path.expanduser(p)).resolve()


def _split_paths(s: str) -> list[Path]:
    parts = [p.strip() for p in s.split(",") if p.strip()]
    return [Path(p).resolve() for p in parts]


def _parse_size(s: str) -> tuple[int, int]:
    # "800x480"
    if "x" not in s:
        raise ValueError(f"Invalid size '{s}' (expected like 800x480)")
    w, h = s.lower().split("x", 1)
    return int(w), int(h)


def _cpu_count() -> int:
    try:
        return multiprocessing.cpu_count()
    except Exception:
        return 4


def _clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


@dataclass(frozen=True)
class Config:
    sd_label: str
    base_output_dir: Path
    db_path: Path

    s3_bucket: str
    s3_prefix_root: str
    presign_expiry_seconds: int

    share_max_long_edge: int
    share_quality: int
    thumb_max_long_edge: int
    thumb_quality: int

    poll_seconds: float

    mount_roots: list[Path]

    status_path: Path
    status_image_path: Path
    status_image_size: tuple[int, int]

    process_workers: int
    upload_workers: int
    presign_workers: int
    hash_workers: int
    copy_workers: int
    
    # Web interface settings
    web_enabled: bool
    web_host: str
    web_port: int

    @property
    def sessions_dir(self) -> Path:
        return self.base_output_dir

    @property
    def volumes_root(self) -> Path:
        # Back-compat: macOS default
        return Path("/Volumes")


def load_config(
    *,
    sd_label: str | None = None,
    base_output_dir: str | None = None,
    db_path: str | None = None,
    s3_bucket: str | None = None,
    s3_prefix_root: str | None = None,
    presign_expiry_seconds: int | None = None,
    share_max_long_edge: int | None = None,
    share_quality: int | None = None,
    thumb_max_long_edge: int | None = None,
    thumb_quality: int | None = None,
    poll_seconds: float | None = None,
    mount_roots: str | None = None,
    status_path: str | None = None,
    status_image_path: str | None = None,
    status_image_size: str | None = None,
    process_workers: int | None = None,
    upload_workers: int | None = None,
    presign_workers: int | None = None,
    hash_workers: int | None = None,
    copy_workers: int | None = None,
    web_enabled: bool | None = None,
    web_host: str | None = None,
    web_port: int | None = None,
) -> Config:
    env = os.environ
    
    # Fallback: If systemd didn't load /etc/ghostroll.env properly, try reading it directly
    # This helps when EnvironmentFile doesn't work as expected
    # Check if key web interface vars are missing or empty (systemd might pass empty strings)
    web_enabled_from_env = env.get("GHOSTROLL_WEB_ENABLED", "").strip()
    if not web_enabled_from_env and Path("/etc/ghostroll.env").exists():
        try:
            env_file_content = Path("/etc/ghostroll.env").read_text(encoding="utf-8")
            for line in env_file_content.splitlines():
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith("#"):
                    continue
                # Parse KEY=VALUE
                if "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")  # Remove quotes if present
                    # Set in environment if not already set or if current value is empty
                    if key.startswith("GHOSTROLL_"):
                        current_value = env.get(key, "").strip()
                        if not current_value:  # If not set or empty, use file value
                            os.environ[key] = value
        except Exception as e:
            # Log error but continue - don't break startup if file read fails
            import sys
            print(f"ghostroll-config: Warning: Could not read /etc/ghostroll.env: {e}", file=sys.stderr)

    sd_label = sd_label or env.get("GHOSTROLL_SD_LABEL", "auto-import")
    base_output_dir = base_output_dir or env.get("GHOSTROLL_BASE_DIR", "~/ghostroll")
    db_path = db_path or env.get("GHOSTROLL_DB_PATH", "~/.ghostroll/ghostroll.db")

    s3_bucket = s3_bucket or env.get("GHOSTROLL_S3_BUCKET", "photo-ingest-project")
    s3_prefix_root = s3_prefix_root or env.get("GHOSTROLL_S3_PREFIX_ROOT", "sessions/")
    presign_expiry_seconds = int(
        presign_expiry_seconds
        if presign_expiry_seconds is not None
        else env.get("GHOSTROLL_PRESIGN_EXPIRY_SECONDS", "604800")
    )

    share_max_long_edge = int(
        share_max_long_edge
        if share_max_long_edge is not None
        else env.get("GHOSTROLL_SHARE_MAX_LONG_EDGE", "2048")
    )
    share_quality = int(
        share_quality if share_quality is not None else env.get("GHOSTROLL_SHARE_QUALITY", "90")
    )
    thumb_max_long_edge = int(
        thumb_max_long_edge
        if thumb_max_long_edge is not None
        else env.get("GHOSTROLL_THUMB_MAX_LONG_EDGE", "512")
    )
    thumb_quality = int(
        thumb_quality if thumb_quality is not None else env.get("GHOSTROLL_THUMB_QUALITY", "85")
    )

    poll_seconds = float(
        poll_seconds if poll_seconds is not None else env.get("GHOSTROLL_POLL_SECONDS", "2")
    )

    mount_roots = mount_roots or env.get("GHOSTROLL_MOUNT_ROOTS", "")
    if mount_roots.strip():
        mount_roots_list = _split_paths(mount_roots)
    else:
        # Reasonable defaults for macOS + Linux.
        mount_roots_list = [Path("/Volumes"), Path("/media"), Path("/run/media"), Path("/mnt")]

    status_path = status_path or env.get("GHOSTROLL_STATUS_PATH", str(_expand("~/ghostroll/status.json")))
    status_image_path = status_image_path or env.get(
        "GHOSTROLL_STATUS_IMAGE_PATH", str(_expand("~/ghostroll/status.png"))
    )
    status_image_size = status_image_size or env.get("GHOSTROLL_STATUS_IMAGE_SIZE", "800x480")

    cpu = _cpu_count()
    process_workers = int(
        process_workers if process_workers is not None else env.get("GHOSTROLL_PROCESS_WORKERS", str(_clamp(cpu, 1, 6)))
    )
    upload_workers = int(
        upload_workers if upload_workers is not None else env.get("GHOSTROLL_UPLOAD_WORKERS", "4")
    )
    presign_workers = int(
        presign_workers if presign_workers is not None else env.get("GHOSTROLL_PRESIGN_WORKERS", "8")
    )
    
    # Hash workers: default to 8 for better I/O parallelism, but allow override
    hash_workers = int(
        hash_workers if hash_workers is not None else env.get("GHOSTROLL_HASH_WORKERS", "8")
    )
    
    # Copy workers: default to 6 for better I/O parallelism during file copying
    copy_workers = int(
        copy_workers if copy_workers is not None else env.get("GHOSTROLL_COPY_WORKERS", "6")
    )
    
    # Web interface settings (enabled by default)
    # Read from environment, handling both explicit values and defaults
    # Systemd passes environment variables as strings, so we need to handle "1", "true", etc.
    web_enabled_env_raw = env.get("GHOSTROLL_WEB_ENABLED", "")
    
    # Debug: log raw value before processing
    import sys
    print(f"ghostroll-config: GHOSTROLL_WEB_ENABLED raw value: {web_enabled_env_raw!r} (type: {type(web_enabled_env_raw).__name__})", file=sys.stderr)
    
    # Handle empty string, whitespace, and None
    if web_enabled_env_raw:
        web_enabled_env = str(web_enabled_env_raw).strip()
    else:
        web_enabled_env = ""
    
    print(f"ghostroll-config: GHOSTROLL_WEB_ENABLED after processing: {web_enabled_env!r}", file=sys.stderr)
    print(f"ghostroll-config: web_enabled CLI arg: {web_enabled}", file=sys.stderr)
    
    if web_enabled is not None:
        # CLI argument takes precedence
        web_enabled = bool(web_enabled)
        print(f"ghostroll-config: Using CLI arg: web_enabled={web_enabled}", file=sys.stderr)
    elif web_enabled_env:
        # Environment variable set - check for truthy values
        web_enabled_env_lower = web_enabled_env.lower()
        print(f"ghostroll-config: Checking env var: '{web_enabled_env_lower}' in truthy values", file=sys.stderr)
        web_enabled = web_enabled_env_lower in ("true", "1", "yes", "on", "enabled")
        print(f"ghostroll-config: Result from env var check: web_enabled={web_enabled}", file=sys.stderr)
    else:
        # Default to enabled if not explicitly set
        web_enabled = True
        print(f"ghostroll-config: Using default: web_enabled={web_enabled}", file=sys.stderr)
    
    web_host = web_host or env.get("GHOSTROLL_WEB_HOST", "127.0.0.1")
    web_port_env = env.get("GHOSTROLL_WEB_PORT", "")
    if web_port_env:
        web_port_env = str(web_port_env).strip()
    else:
        web_port_env = ""
    
    if web_port is not None:
        web_port = int(web_port)
    elif web_port_env:
        try:
            web_port = int(web_port_env)
        except ValueError:
            # Invalid port, use default
            web_port = 8080
    else:
        # Default port (8080 on macOS/Linux, 8081 on Pi if WiFi portal uses 8080)
        web_port = 8080

    cfg = Config(
        sd_label=sd_label,
        base_output_dir=_expand(base_output_dir),
        db_path=_expand(db_path),
        s3_bucket=s3_bucket,
        s3_prefix_root=s3_prefix_root if s3_prefix_root.endswith("/") else (s3_prefix_root + "/"),
        presign_expiry_seconds=presign_expiry_seconds,
        share_max_long_edge=share_max_long_edge,
        share_quality=share_quality,
        thumb_max_long_edge=thumb_max_long_edge,
        thumb_quality=thumb_quality,
        poll_seconds=poll_seconds,
        mount_roots=mount_roots_list,
        status_path=_expand(status_path),
        status_image_path=_expand(status_image_path),
        status_image_size=_parse_size(status_image_size),
        process_workers=process_workers,
        upload_workers=upload_workers,
        presign_workers=presign_workers,
        hash_workers=hash_workers,
        copy_workers=copy_workers,
        web_enabled=web_enabled,
        web_host=web_host,
        web_port=web_port,
    )

    cfg.base_output_dir.mkdir(parents=True, exist_ok=True)
    cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.status_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.status_image_path.parent.mkdir(parents=True, exist_ok=True)
    return cfg


