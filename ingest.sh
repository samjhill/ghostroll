#!/usr/bin/env bash
set -euo pipefail

BUCKET="photo-ingest-project"
REMOTE="ghostroll"          # rclone remote name
TARGET_LABEL="auto-import"  # SD volume label to watch

BASE="$HOME/ghostroll"

pick_volume() {
  # Prefer exact match, then any suffix match
  if [[ -d "/Volumes/${TARGET_LABEL}" ]]; then
    echo "/Volumes/${TARGET_LABEL}"
    return 0
  fi
  for v in /Volumes/"${TARGET_LABEL}"*; do
    [[ -d "$v" ]] || continue
    echo "$v"
    return 0
  done
  return 1
}

echo "👻 GhostRoll watching for SD volume '${TARGET_LABEL}'..."
echo "Insert the SD card to begin."

while true; do
  if VOLPATH="$(pick_volume)"; then
    echo "✅ Detected volume: $VOLPATH"

    DCIM="${VOLPATH}/DCIM"
    if [[ ! -d "$DCIM" ]]; then
      echo "⚠️ DCIM not found at ${DCIM}. Not a camera card? Waiting..."
      sleep 2
      continue
    fi

    SESSION_ID="shoot-$(date +%F_%H%M%S)"
    SESSION_DIR="${BASE}/${SESSION_ID}"
    ORIG="${SESSION_DIR}/originals"
    SHARE="${SESSION_DIR}/derived/share"
    THUMBS="${SESSION_DIR}/derived/thumbs"
    INDEX="${SESSION_DIR}/index.html"

    mkdir -p "$ORIG" "$SHARE" "$THUMBS"

    echo "📥 Ingesting from $DCIM -> $ORIG"
    rsync -a --ignore-existing "$DCIM/" "$ORIG/DCIM/"

    echo "🧪 Processing JPEGs -> share/thumbs"
    find "$ORIG" -type f \( -iname "*.jpg" -o -iname "*.jpeg" \) -print0 | while IFS= read -r -d '' f; do
      base="$(basename "$f")"
      magick "$f" -auto-orient -resize 2048x2048\> -strip -quality 90 "$SHARE/$base"
      magick "$f" -auto-orient -resize 512x512\> -strip -quality 85 "$THUMBS/$base"
    done

    echo "🧩 Building index.html"
    cat > "$INDEX" <<HTML
<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${SESSION_ID}</title>
<style>
body{font-family:system-ui;margin:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px}
a{display:block}
img{width:100%;height:auto;border-radius:10px}
</style></head><body>
<h1>${SESSION_ID}</h1>
<div class="grid">
HTML

    shopt -s nullglob
    for t in "$THUMBS"/*; do
      b="$(basename "$t")"
      echo "  <a href=\"share/${b}\"><img src=\"thumbs/${b}\" loading=\"lazy\"></a>" >> "$INDEX"
    done
    cat >> "$INDEX" <<'HTML'
</div></body></html>
HTML

    PREFIX="sessions/${SESSION_ID}"

    echo "☁️ Uploading to s3://${BUCKET}/${PREFIX}/"
    rclone copy "$SHARE"  "${REMOTE}:${BUCKET}/${PREFIX}/share"
    rclone copy "$THUMBS" "${REMOTE}:${BUCKET}/${PREFIX}/thumbs"
    rclone copy "$INDEX"  "${REMOTE}:${BUCKET}/${PREFIX}"

    echo "🔗 Generating presigned share link (7 days)"
    URL="$(aws s3 presign "s3://${BUCKET}/${PREFIX}/index.html" --expires-in 604800)"
    echo "$URL" | tee "${SESSION_DIR}/share.txt"

    echo "✅ Done. Share link saved to: ${SESSION_DIR}/share.txt"
    echo "Remove SD card to run again."

    # Wait until volume disappears before allowing another run
    while pick_volume >/dev/null 2>&1; do sleep 2; done
    echo "👻 Waiting for next '${TARGET_LABEL}' card..."
  else
    sleep 2
  fi
done
SH