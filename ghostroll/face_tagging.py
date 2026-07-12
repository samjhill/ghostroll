"""
Optional face detection + coarse per-session clustering for gallery filters.

Requires the optional ``ghostroll[faces]`` extra (OpenCV). When OpenCV is not
installed, helpers no-op with a log line.

Clustering uses 64-bit **difference** and **average** hashes of each face crop.
Two detections are linked if **either** hash is within the Hamming threshold
(union–find over those edges), which merges more same-person views than d-hash
alone. Overlapping Haar rectangles are merged with NMS to cut duplicate boxes.
This remains a lightweight heuristic (not identity-grade recognition).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageOps

MODEL_ID = "ghostroll-opencv-dahash-v2"


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


def ahash64(gray: Image.Image) -> int:
    """8×8 average hash as a 64-bit int (Pillow grayscale image)."""
    g = gray.resize((8, 8), Image.Resampling.BILINEAR)
    px = list(g.getdata())
    mean = sum(px) / len(px) if px else 0.0
    bits = 0
    for p in px:
        bits = (bits << 1) | (1 if p >= mean else 0)
    return bits & ((1 << 64) - 1)


def hamming64(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def default_face_cluster_hamming_max() -> int:
    """Clamp for ``GHOSTROLL_FACE_HAMMING_MAX`` (Hamming on d-hash and a-hash OR-link)."""
    try:
        mh = int(os.environ.get("GHOSTROLL_FACE_HAMMING_MAX", "26"))
    except Exception:
        mh = 26
    return max(4, min(32, mh))


def _iou_xywh(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    xa1, ya1, xa2, ya2 = ax, ay, ax + aw, ay + ah
    xb1, yb1, xb2, yb2 = bx, by, bx + bw, by + bh
    inter_w = max(0, min(xa2, xb2) - max(xa1, xb1))
    inter_h = max(0, min(ya2, yb2) - max(ya1, yb1))
    inter = inter_w * inter_h
    union = aw * ah + bw * bh - inter
    if union <= 0:
        return 0.0
    return inter / union


def _nms_face_boxes(
    boxes: list[tuple[int, int, int, int]],
    *,
    iou_threshold: float = 0.35,
) -> list[tuple[int, int, int, int]]:
    """Drop overlapping Haar boxes (keeps larger box first)."""
    if not boxes:
        return []
    sorted_boxes = sorted(boxes, key=lambda b: -(b[2] * b[3]))
    kept: list[tuple[int, int, int, int]] = []
    for b in sorted_boxes:
        if any(_iou_xywh(b, k) > iou_threshold for k in kept):
            continue
        kept.append(b)
    return kept


@dataclass
class FaceSample:
    rel: Path  # relative to share root
    box: tuple[int, int, int, int]  # x, y, w, h in pixels
    h: int  # d-hash
    ha: int  # average hash (used with ``h`` for clustering)


def _detect_faces_cv2(cv2, rgb_path: Path) -> list[tuple[int, int, int, int]]:
    cascade_path = str(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    face_cascade = cv2.CascadeClassifier(cascade_path)
    if face_cascade.empty():
        return []
    bgr = cv2.imread(str(rgb_path))
    if bgr is None:
        return []
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    raw = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(56, 56))
    boxes = [(int(x), int(y), int(w), int(h)) for (x, y, w, h) in raw]
    return _nms_face_boxes(boxes, iou_threshold=0.35)


def _face_hashes_from_crop(rgb_path: Path, box: tuple[int, int, int, int]) -> tuple[int, int] | None:
    try:
        with Image.open(rgb_path) as im:
            im = ImageOps.exif_transpose(im)
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            x, y, w, h = box
            crop = im.crop((x, y, x + w, y + h)).convert("L")
            crop = crop.resize((64, 64), Image.Resampling.BILINEAR)
            return (dhash64(crop), ahash64(crop))
    except Exception:
        return None


def collect_face_samples(
    share_dir: Path,
    *,
    cv2,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[FaceSample]:
    samples: list[FaceSample] = []
    image_paths = sorted(
        p
        for p in share_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg")
    )
    total = len(image_paths)
    for i, p in enumerate(image_paths, 1):
        boxes = _detect_faces_cv2(cv2, p)
        rel = p.relative_to(share_dir)
        for box in boxes:
            pair = _face_hashes_from_crop(p, box)
            if pair is None:
                continue
            h, ha = pair
            samples.append(FaceSample(rel=rel, box=box, h=h, ha=ha))
        if progress_callback is not None:
            progress_callback(i, total)
    return samples


def cluster_face_samples(samples: list[FaceSample], *, max_hamming: int) -> list[int]:
    """
    Return cluster index per sample using single-linkage (union–find).

    An edge exists between two samples when **either** the d-hash or the average-hash
    Hamming distance is ≤ ``max_hamming``. That OR-link merges more same-person crops
    than d-hash alone while staying cheap.
    """
    n = len(samples)
    if n == 0:
        return []
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        pi, pj = find(i), find(j)
        if pi != pj:
            parent[pi] = pj

    hashes_d = [s.h for s in samples]
    hashes_a = [s.ha for s in samples]
    for i in range(n):
        di, ai = hashes_d[i], hashes_a[i]
        for j in range(i + 1, n):
            if hamming64(di, hashes_d[j]) <= max_hamming or hamming64(ai, hashes_a[j]) <= max_hamming:
                union(i, j)

    root_to_ci: dict[int, int] = {}
    out: list[int] = []
    next_ci = 0
    for i in range(n):
        r = find(i)
        if r not in root_to_ci:
            root_to_ci[r] = next_ci
            next_ci += 1
        out.append(root_to_ci[r])
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
    progress_callback: Callable[[int, int], None] | None = None,
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

    mh = default_face_cluster_hamming_max() if max_hamming is None else max(4, min(32, int(max_hamming)))

    samples = collect_face_samples(
        derived_share_dir,
        cv2=cv2,
        progress_callback=progress_callback,
    )
    if not samples:
        logger.info("Face tagging: no faces detected in session share images.")
        return 0

    cluster_of = cluster_face_samples(samples, max_hamming=mh)
    n_clusters = max(cluster_of, default=-1) + 1 if cluster_of else 0
    logger.info(
        "Face tagging: %s face crop(s) -> %s person cluster(s) (Hamming≤%s on d-hash or avg-hash; NMS on detector boxes)",
        len(samples),
        n_clusters,
        mh,
    )
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


def upload_face_tags_for_session_to_s3(*, cfg: Any, session_id: str, logger: Any) -> int:
    """
    Detect faces in local ``derived/share`` JPEGs and upload merged ``tags/*.json`` to S3.

    Used for backfill (e.g. ``republish-gallery SESSION --face-tags``) when share images
    exist under ``{base_output_dir}/{session_id}`` but tags were never uploaded.
    """
    session_dir = Path(cfg.base_output_dir) / session_id
    derived_share_dir = session_dir / "derived" / "share"
    prefix = f"{cfg.s3_prefix_root}{session_id}".rstrip("/")
    if not derived_share_dir.is_dir():
        logger.warning("Face tags: missing local directory %s (skipping)", derived_share_dir)
        return 0

    from ghostroll.aws_boto3 import AwsBoto3Error, s3_upload_file

    def upload_one(pair: tuple[Path, str]) -> tuple[bool, str | None]:
        local_path, key = pair
        try:
            s3_upload_file(local_path, bucket=cfg.s3_bucket, key=key)
            return True, None
        except AwsBoto3Error as e:
            return False, str(e).split("\n")[0]

    return write_and_upload_face_tags_for_session(
        cfg=cfg,
        session_dir=session_dir,
        derived_share_dir=derived_share_dir,
        prefix=prefix,
        upload_one=upload_one,
        logger=logger,
    )


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
    cluster_of = cluster_face_samples(samples, max_hamming=default_face_cluster_hamming_max())
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
