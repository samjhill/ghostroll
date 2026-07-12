from __future__ import annotations

from pathlib import Path

import pytest

from ghostroll.face_tagging import (
    build_face_payload_for_image,
    cluster_face_samples,
    dhash64,
    default_face_cluster_hamming_max,
    hamming64,
    merge_tag_sidecars,
    person_label,
    FaceSample,
)


def test_dhash_hamming_stable():
    from PIL import Image

    g1 = Image.new("L", (8, 8), color=200)
    g2 = Image.new("L", (8, 8), color=198)
    h1 = dhash64(g1)
    h2 = dhash64(g2)
    assert hamming64(h1, h2) <= 4


def test_cluster_face_samples_groups_similar():
    samples = [
        FaceSample(rel=Path("a.jpg"), box=(0, 0, 10, 10), h=0xFFFF_FFFF_FFFF_FFFF, ha=0xFFFF_FFFF_FFFF_FFFF),
        FaceSample(rel=Path("b.jpg"), box=(1, 1, 10, 10), h=0xFFFF_FFFF_FFFF_FFFF, ha=0xFFFF_FFFF_FFFF_FFFF),
        FaceSample(rel=Path("c.jpg"), box=(2, 2, 10, 10), h=0x0000_0000_0000_0001, ha=0x0000_0000_0000_0001),
    ]
    clusters = cluster_face_samples(samples, max_hamming=2)
    assert clusters[0] == clusters[1]
    assert clusters[2] != clusters[0]


def test_cluster_face_samples_merges_transitive_chains():
    """A–B and B–C are within threshold but A–C are not; single-linkage still merges one identity."""
    h_a = 0
    h_b = (1 << 6) - 1
    h_c = h_b | (((1 << 6) - 1) << 20)
    assert hamming64(h_a, h_b) == 6
    assert hamming64(h_b, h_c) == 6
    assert hamming64(h_a, h_c) == 12
    samples = [
        FaceSample(rel=Path("a.jpg"), box=(0, 0, 1, 1), h=h_a, ha=h_a),
        FaceSample(rel=Path("b.jpg"), box=(0, 0, 1, 1), h=h_b, ha=h_b),
        FaceSample(rel=Path("c.jpg"), box=(0, 0, 1, 1), h=h_c, ha=h_c),
    ]
    clusters = cluster_face_samples(samples, max_hamming=10)
    assert clusters[0] == clusters[1] == clusters[2]


def test_cluster_face_samples_or_merge_when_only_ahash_matches():
    """d-hashes far apart but identical average-hash still links (OR edge)."""
    d1, d2 = 0xFFFF_FFFF_FFFF_FFFF, 0x0000_0000_0000_00FF
    a_same = 0x5555_5555_5555_5555
    assert hamming64(d1, d2) > 8
    samples = [
        FaceSample(rel=Path("a.jpg"), box=(0, 0, 1, 1), h=d1, ha=a_same),
        FaceSample(rel=Path("b.jpg"), box=(0, 0, 1, 1), h=d2, ha=a_same),
    ]
    clusters = cluster_face_samples(samples, max_hamming=8)
    assert clusters[0] == clusters[1]


def test_default_face_cluster_hamming_max_clamped(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GHOSTROLL_FACE_HAMMING_MAX", "99")
    assert default_face_cluster_hamming_max() == 32
    monkeypatch.setenv("GHOSTROLL_FACE_HAMMING_MAX", "1")
    assert default_face_cluster_hamming_max() == 4


def test_merge_tag_sidecars_keeps_rekognition_and_faces():
    rek = {
        "model": "aws",
        "labels": [{"name": "Sky", "confidence": 90.0, "parents": []}],
    }
    face_doc = build_face_payload_for_image(
        Path("x/y.jpg"),
        [((0, 0, 4, 4), person_label(0), 0.99)],
    )
    merged = merge_tag_sidecars(rekognition_like=rek, face_payload=face_doc)
    names = {x["name"] for x in merged["labels"]}
    assert "Sky" in names
    assert "Person 1" in names
    assert len(merged["faces"]) == 1


def test_build_index_html_includes_face_filter_placeholder(tmp_path: Path):
    from ghostroll.gallery import build_index_html_from_items

    items = [
        (
            "t.jpg",
            "s.jpg",
            "t",
            "",
            None,
            "tags/x.json",
        )
    ]
    out = tmp_path / "index.html"
    build_index_html_from_items(session_id="s", items=items, download_href=None, out_path=out)
    html = out.read_text(encoding="utf-8")
    assert "Filter by person or tag" in html
    assert "tagStripInnerFaces" in html
    assert "tagStripInnerLabels" in html
    assert "tags/x.json" in html
