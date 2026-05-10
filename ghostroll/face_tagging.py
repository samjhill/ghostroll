"""
Optional face detection + coarse per-session clustering for gallery filters.

Requires the optional ``ghostroll[faces]`` extra (OpenCV). When OpenCV is not
installed, helpers no-op with a log line.

Clustering uses a 64-bit difference hash of each face crop; faces with Hamming
distance below a threshold in the same session are grouped as ``Person 1``,
``Person 2``, … This is a lightweight heuristic (not identity-grade recognition).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageOps

MODEL_ID = "ghostroll-opencv-dhash-v1"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _try_import_cv2():  # pragma: no cover - import guard
    try:
        import cv2  # type: ignore[import-not-found]

        return cv2
    except Exception:
        return None


def dhash64(gray: Image.Image) -> int:
    """8×8 difference hash as a 64-bit int (Pillow grayscale image)."""
    g = gray.resize((9, 8), Image.Resampling.BILINEAR)
    bits = 0
    for row in range(8):
        for col in range(8):
            left = g.getpixel((col, row))
            right = g.getpixel((col + 1, row))
            bits = (bits << 1) | (1 if left > right else 0)
    return bits & ((1 << 64) - 1)


def hamming64(a: int, b: int) -> int:
    return (a ^ b).bit_count()


@dataclass
class FaceSample:
    rel: Path  # relative to share root
    box: tuple[int, int, int, int]  # x, y, w, h in pixels
    h: int


def _detect_faces_cv2(cv2, rgb_path: Path) -> list[tuple[int, int, int, int]]:
    cascade_path = str(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    face_cascade = cv2.CascadeClassifier(cascade_path)
    if face_cascade.empty():
        return []
    bgr = cv2.imread(str(rgb_path))
    if bgr is None:
        return []
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(48, 48))
    return [(int(x), int(y), int(w), int(h)) for (x, y, w, h) in faces]


def _face_hash_from_crop(rgb_path: Path, box: tuple[int, int, int, int]) -> int | None:
    try:
        with Image.open(rgb_path) as im:
            im = ImageOps.exif_transpose(im)
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            x, y, w, h = box
            crop = im.crop((x, y, x + w, y + h)).convert("L")
            crop = crop.resize((64, 64), Image.Resampling.BILINEAR)
            return dhash64(crop)
    except Exception:
        return None


def collect_face_samples(share_dir: Path, *, cv2) -> list[FaceSample]:
    samples: list[FaceSample] = []
    for p in sorted(share_dir.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in (".jpg", ".jpeg"):
            continue
        boxes = _detect_faces_cv2(cv2, p)
        rel = p.relative_to(share_dir)
        for box in boxes:
            h = _face_hash_from_crop(p, box)
            if h is None:
                continue
            samples.append(FaceSample(rel=rel, box=box, h=h))
    return samples


def cluster_face_samples(samples: list[FaceSample], *, max_hamming: int) -> list[int]:
    """Returns cluster index per sample (greedy, order-dependent)."""
    clusters: list[list[FaceSample]] = []
    out: list[int] = []
    for s in samples:
        best_ci: int | None = None
        best_d = max_hamming + 1
        for ci, members in enumerate(clusters):
            for m in members:
                d = hamming64(s.h, m.h)
                if d < best_d:
                    best_d = d
                    best_ci = ci
        if best_ci is None or best_d > max_hamming:
            clusters.append([s])
            out.append(len(clusters) - 1)
        else:
            clusters[best_ci].append(s)
            out.append(best_ci)
    return out


def person_label(cluster_index: int) -> str:
    return f"Person {cluster_index + 1}"


def build_face_payload_for_image(
    rel: Path,
    entries: list[tuple[tuple[int, int, int, int], str, float]],
) -> dict[str, Any]:
    labels: list[dict[str, Any]] = []
    faces_out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for box, person, conf in entries:
        faces_out.append(
            {
                "person": person,
                "box": [int(box[0]), int(box[1]), int(box[2]), int(box[3])],
                "confidence": float(conf),
            }
        )
        key = person.lower()
        if key not in seen:
            seen.add(key)
            labels.append(
                {
                    "name": person,
                    "confidence": 100.0,
                    "parents": ["Face"],
                }
            )
    return {
        "model_faces": MODEL_ID,
        "generated_utc_faces": _utc_now_iso(),
        "source_relpath": rel.as_posix(),
        "faces": faces_out,
        "labels_faces": labels,
    }


def merge_tag_sidecars(*, rekognition_like: dict[str, Any] | None, face_payload: dict[str, Any]) -> dict[str, Any]:
    """
    Merge Rekognition-style tag JSON (labels, model, …) with face payload.

    Face-specific keys are stored under ``faces`` / ``model_faces``; person
    names are also appended to ``labels`` for gallery text search / chips.
    """
    base: dict[str, Any] = dict(rekognition_like) if rekognition_like else {}
    base["faces"] = face_payload.get("faces") or []
    base["model_faces"] = face_payload.get("model_faces", MODEL_ID)
    base["generated_utc_faces"] = face_payload.get("generated_utc_faces", _utc_now_iso())

    merged_labels: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for src in (base.get("labels") or []):
        if isinstance(src, dict) and src.get("name"):
            nm = str(src["name"])
            key = nm.lower()
            if key not in seen_names:
                seen_names.add(key)
                merged_labels.append(src)
    for src in face_payload.get("labels_faces") or []:
        if isinstance(src, dict) and src.get("name"):
            nm = str(src["name"])
            key = nm.lower()
            if key not in seen_names:
                seen_names.add(key)
                merged_labels.append(src)
    base["labels"] = merged_labels
    return base


def write_and_upload_face_tags_for_session(
    *,
    cfg: Any,
    session_dir: Path,
    derived_share_dir: Path,
    prefix: str,
    upload_one: Callable[[tuple[Path, str]], tuple[bool, str | None]],
    logger: Any,
    max_hamming: int | None = None,
) -> int:
    """
    Detect faces in all share JPEGs, cluster within the session, write merged
    ``tags/*.json`` under the session dir, and upload to ``{prefix}/tags/…``.

    Returns number of tag JSON files uploaded.
    """
    cv2 = _try_import_cv2()
    if cv2 is None:
        logger.warning(
            "Face tagging is enabled but OpenCV is not installed. "
            "Install optional deps: pip install 'ghostroll[faces]'"
        )
        return 0

    mh = max_hamming
    if mh is None:
        try:
            mh = int(os.environ.get("GHOSTROLL_FACE_HAMMING_MAX", "12"))
        except Exception:
            mh = 12
    mh = max(4, min(32, mh))

    samples = collect_face_samples(derived_share_dir, cv2=cv2)
    if not samples:
        logger.info("Face tagging: no faces detected in session share images.")
        return 0

    cluster_of = cluster_face_samples(samples, max_hamming=mh)
    by_rel: dict[Path, list[tuple[tuple[int, int, int, int], str, float]]] = {}
    for s, ci in zip(samples, cluster_of, strict=True):
        person = person_label(ci)
        by_rel.setdefault(s.rel, []).append((s.box, person, 0.99))

    tags_dir = session_dir / "tags"
    tags_dir.mkdir(parents=True, exist_ok=True)

    from ghostroll.aws_boto3 import AwsBoto3Error, s3_get_json, s3_object_exists

    uploaded = 0
    for rel, entries in sorted(by_rel.items(), key=lambda kv: kv[0].as_posix()):
        face_doc = build_face_payload_for_image(rel, entries)
        tags_key = f"{prefix}/tags/{rel.with_suffix('.json').as_posix()}"
        existing: dict[str, Any] | None = None
        if s3_object_exists(bucket=cfg.s3_bucket, key=tags_key):
            try:
                existing = s3_get_json(bucket=cfg.s3_bucket, key=tags_key)
            except AwsBoto3Error:
                existing = None
        merged = merge_tag_sidecars(rekognition_like=existing, face_payload=face_doc)
        out_path = tags_dir / rel.with_suffix(".json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        ok, err = upload_one((out_path, tags_key))
        if ok:
            uploaded += 1
        elif err:
            logger.warning(f"Face tags upload failed for {tags_key}: {err}")
    logger.info(f"Face tagging: uploaded {uploaded} tag sidecar(s) with person clusters (model={MODEL_ID}).")
    return uploaded


def cmd_tag_faces_session(session_dir: Path, *, logger: Any) -> int:
    """CLI helper: write merged tag JSON locally (no S3)."""
    cv2 = _try_import_cv2()
    if cv2 is None:
        logger.error("OpenCV required: pip install 'ghostroll[faces]'")
        return 2
    share_dir = session_dir / "derived" / "share"
    if not share_dir.is_dir():
        logger.error(f"No derived/share directory: {share_dir}")
        return 2
    samples = collect_face_samples(share_dir, cv2=cv2)
    if not samples:
        logger.info("No faces detected.")
        return 0
    cluster_of = cluster_face_samples(samples, max_hamming=12)
    by_rel: dict[Path, list[tuple[tuple[int, int, int, int], str, float]]] = {}
    for s, ci in zip(samples, cluster_of, strict=True):
        by_rel.setdefault(s.rel, []).append((s.box, person_label(ci), 0.99))
    tags_dir = session_dir / "tags"
    tags_dir.mkdir(parents=True, exist_ok=True)
    for rel, entries in sorted(by_rel.items(), key=lambda kv: kv[0].as_posix()):
        face_doc = build_face_payload_for_image(rel, entries)
        merged = merge_tag_sidecars(rekognition_like=None, face_payload=face_doc)
        out_path = tags_dir / rel.with_suffix(".json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        logger.info(f"Wrote {out_path}")
    return 0
