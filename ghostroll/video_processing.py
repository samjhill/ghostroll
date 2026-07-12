from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class VideoProcessingError(Exception):
    pass


def _run(cmd: list[str], *, logger=None) -> None:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError as e:
        raise VideoProcessingError(
            "ffmpeg/ffprobe not found. Install ffmpeg to process videos."
        ) from e
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise VideoProcessingError(err or f"Command failed: {' '.join(cmd)}")


def render_video_derivatives(
    *,
    src: Path,
    video_out: Path,
    poster_out: Path,
    logger=None,
    poster_max_edge: int = 1280,
) -> None:
    """
    Produce a browser-friendly MP4 (H.264 + AAC, faststart) and a JPEG poster frame.
    """
    if shutil.which("ffmpeg") is None:
        raise VideoProcessingError("ffmpeg not found on PATH")

    video_out.parent.mkdir(parents=True, exist_ok=True)
    poster_out.parent.mkdir(parents=True, exist_ok=True)

    if logger:
        logger.debug(f"  Transcoding video: {src.name} -> {video_out.name}")

    _run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(src),
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(video_out),
        ],
        logger=logger,
    )

    if logger:
        logger.debug(f"  Extracting poster: {poster_out.name}")

    _run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            "1",
            "-i",
            str(video_out if video_out.exists() else src),
            "-frames:v",
            "1",
            "-vf",
            f"scale='min({poster_max_edge},iw)':-2",
            "-q:v",
            "3",
            str(poster_out),
        ],
        logger=logger,
    )

    if not video_out.exists() or video_out.stat().st_size == 0:
        raise VideoProcessingError(f"Video output missing or empty: {video_out}")
    if not poster_out.exists() or poster_out.stat().st_size == 0:
        raise VideoProcessingError(f"Poster output missing or empty: {poster_out}")
