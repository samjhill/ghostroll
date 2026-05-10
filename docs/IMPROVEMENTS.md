# GhostRoll: improvement ideas

This note captures practical directions for evolving GhostRoll beyond the current design (SD card → local session → derived assets → private S3 → presigned HTML gallery, optional Lambda enhancement, Rekognition-style tag sidecars, optional face clustering).

## Product and sharing

- **Presigned URL lifetime**: URLs embedded in HTML eventually expire; recipients see broken images or a dead gallery. Mitigations include documenting operational steps (for example `ghostroll republish-gallery`), tuning `GHOSTROLL` presign expiry where acceptable, or moving to **CloudFront with short-lived signed cookies** / a small **authenticated redirect** so the link people share stays stable while credentials rotate underneath.
- **Stable “session home”**: A single canonical URL that always resolves to the latest gallery bundle (even a minimal serverless redirector) reduces confusion compared to many long presigned query strings.

## Gallery (HTML / JS)

- **Maintainability**: Much of the UI lives as large inline strings in `ghostroll/gallery.py`. Splitting markup, CSS, and behavior into static assets or templates improves review, formatting, optional minification, and reuse.
- **Large galleries**: For hundreds of images, consider **virtualizing** the grid, tuning lazy loading, or paginating so mobile browsers stay responsive.
- **Tag loading**: Today the page may fetch many per-image tag JSON files. Building a **single session-level tag index** at ingest time would cut round trips and allow smarter ranking, grouping, or caps before HTML is generated.
- **Collapsed tag UI**: When tag controls live inside `<details>`, a small **“filter active”** indicator on the summary (when the search box is non-empty) keeps state visible without expanding the panel.

## Pipeline and operations

- **Admin-style CLIs**: `republish-gallery` is a useful pattern; similar commands could rebuild status artifacts, refresh `share.txt`, validate expected S3 key layout, or **dry-run** uploads.
- **Observability**: Structured logs and simple metrics (per-step durations, bytes uploaded, failure counts)—especially on Raspberry Pi and flaky networks—make production issues faster to diagnose.
- **Retries**: Centralized S3 upload policy (backoff, jitter, idempotency) and surfacing “degraded but resumable” in `status.json` improves trust on slow links.

## Quality and safety

- **Testing**: Expand integration coverage (for example moto-backed S3, full session directories). If gallery JavaScript is extracted, add lightweight browser smoke tests or unit tests on extracted modules.
- **Secrets and logs**: Document that presigned URLs are bearer credentials; avoid committing them; rotate keys if leaked. Consider redacting query strings in automated log upload paths.
- **Face tagging**: Current OpenCV + dHash clustering is intentionally coarse, not identity-grade recognition. Clear in-product copy and an optional upgrade path (stronger embeddings) would set expectations.

## Configuration and packaging

- **Validated configuration**: A single schema-validated config (with something like `ghostroll config --show` / `--check`) reduces “works on my machine” drift between environments.
- **Optional extras**: Keep core `pip install ghostroll` lean; group optional stacks (`faces`, dev tools, web helpers) in `pyproject.toml` extras.

## Documentation

- **Sharing model**: A short doc that explains presigns, expiry, republish, and QR/`share.txt` together answers the most common operator questions in one place.

---

Contributions welcome: pick an area, open an issue or PR with a narrow scope, and link back to this list if useful.
