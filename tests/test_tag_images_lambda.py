import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError


def _load_lambda_module():
    repo_root = Path(__file__).resolve().parents[1]
    mod_path = repo_root / "aws-lambda" / "tag-images" / "lambda_function.py"
    spec = importlib.util.spec_from_file_location("ghostroll_tag_images_lambda", mod_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


class FakeS3:
    def __init__(self):
        self.existing: set[tuple[str, str]] = set()
        self.bodies: dict[tuple[str, str], bytes] = {}
        self.puts: list[dict] = []
        self.head_calls: list[tuple[str, str]] = []

    def head_object(self, Bucket: str, Key: str):
        self.head_calls.append((Bucket, Key))
        if (Bucket, Key) in self.existing:
            return {"ResponseMetadata": {"HTTPStatusCode": 200}}
        raise ClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
            "HeadObject",
        )

    def get_object(self, Bucket: str, Key: str):
        bk = (Bucket, Key)
        if bk not in self.bodies:
            raise ClientError(
                {"Error": {"Code": "404", "Message": "Not Found"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
                "GetObject",
            )
        return {"Body": io.BytesIO(self.bodies[bk])}

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        bk = (kwargs["Bucket"], kwargs["Key"])
        body = kwargs["Body"]
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.bodies[bk] = body
        self.existing.add(bk)
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}


class FakeRekognition:
    def __init__(self, labels=None):
        self.calls: list[dict] = []
        self.labels = labels or [
            {"Name": "Cat", "Confidence": 99.0, "Parents": [{"Name": "Animal"}]},
            {"Name": "Indoor", "Confidence": 88.0, "Parents": []},
        ]

    def detect_labels(self, **kwargs):
        self.calls.append(kwargs)
        return {"Labels": self.labels}


def _install_clients(mod, s3: FakeS3, rek: FakeRekognition):
    mod.s3_client = s3
    mod.rekognition_client = rek


def test_get_tags_key_swaps_share_and_extension():
    mod = _load_lambda_module()
    mod.TAGS_PREFIX = "tags"
    assert (
        mod.get_tags_key("sessions/s1/share/IMG_001.jpg")
        == "sessions/s1/tags/IMG_001.json"
    )
    assert (
        mod.get_tags_key("sessions/s1/share/IMG_001.JPEG")
        == "sessions/s1/tags/IMG_001.json"
    )


def test_process_image_skips_non_jpeg_and_non_share():
    mod = _load_lambda_module()
    s3 = FakeS3()
    rek = FakeRekognition()
    _install_clients(mod, s3, rek)

    r1 = mod.process_image("b", "sessions/s1/share/IMG_001.png")
    assert r1["status"] == "skipped"
    assert r1["reason"] == "not_a_jpeg"
    assert rek.calls == []

    r2 = mod.process_image("b", "sessions/s1/other/IMG_001.jpg")
    assert r2["status"] == "skipped"
    assert r2["reason"] == "not_in_share_prefix"
    assert rek.calls == []


def test_process_image_merges_rekognition_when_tags_sidecar_exists():
    mod = _load_lambda_module()
    s3 = FakeS3()
    rek = FakeRekognition()
    _install_clients(mod, s3, rek)

    key = "sessions/s1/share/IMG_001.jpg"
    tags_key = "sessions/s1/tags/IMG_001.json"
    existing = {
        "faces": [{"person": "Person 1", "box": [0, 0, 1, 1], "confidence": 0.99}],
        "model_faces": "ghostroll-test",
        "labels": [],
    }
    s3.bodies[("b", tags_key)] = (json.dumps(existing) + "\n").encode("utf-8")
    s3.existing.add(("b", tags_key))

    out = mod.process_image("b", key)
    assert out["status"] == "success"
    assert len(rek.calls) == 1
    assert len(s3.puts) == 1
    merged = json.loads(s3.puts[0]["Body"].decode("utf-8"))
    assert merged.get("faces") == existing["faces"]
    names = {lbl["name"] for lbl in merged.get("labels", [])}
    assert "Cat" in names
    assert "Indoor" in names


def test_process_image_writes_sorted_labels_json():
    mod = _load_lambda_module()
    s3 = FakeS3()
    rek = FakeRekognition(
        labels=[
            {"Name": "B", "Confidence": 50.0, "Parents": []},
            {"Name": "A", "Confidence": 99.0, "Parents": []},
        ]
    )
    _install_clients(mod, s3, rek)

    out = mod.process_image("b", "sessions/s1/share/IMG_001.jpg")
    assert out["status"] == "success"
    assert len(rek.calls) == 1
    assert len(s3.puts) == 1
    body = s3.puts[0]["Body"].decode("utf-8")
    assert "\"labels\"" in body
    # confidence desc => A before B
    assert body.find("\"name\":\"A\"") < body.find("\"name\":\"B\"")


def test_lambda_handler_supports_s3_records_and_eventbridge():
    mod = _load_lambda_module()
    s3 = FakeS3()
    rek = FakeRekognition()
    _install_clients(mod, s3, rek)

    mod.S3_BUCKET = "b"  # prefer env bucket to avoid relying on event

    evt_s3 = {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": "ignored"},
                    "object": {"key": "sessions/s1/share/IMG_001.jpg"},
                }
            }
        ]
    }
    r1 = mod.lambda_handler(evt_s3, SimpleNamespace())
    assert r1["statusCode"] in (200, 207)

    evt_eb = {
        "source": "aws.s3",
        "detail": {"bucket": {"name": "ignored"}, "object": {"key": "sessions/s1/share/IMG_002.jpg"}},
    }
    r2 = mod.lambda_handler(evt_eb, SimpleNamespace())
    assert r2["statusCode"] in (200, 207)


def test_lambda_handler_returns_400_without_bucket():
    mod = _load_lambda_module()
    s3 = FakeS3()
    rek = FakeRekognition()
    _install_clients(mod, s3, rek)
    mod.S3_BUCKET = ""

    r = mod.lambda_handler({"Records": []}, SimpleNamespace())
    assert r["statusCode"] == 400

