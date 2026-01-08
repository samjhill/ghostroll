from __future__ import annotations

from pathlib import Path


class QrError(RuntimeError):
    pass


def write_qr_png(*, data: str, out_path: Path) -> None:
    """
    Writes a QR code PNG for the given string.
    """
    try:
        import qrcode
    except ImportError as e:
        raise QrError(
            "QR code generation requires the 'qrcode' package.\n"
            "  Install with: pip install qrcode[pil]\n"
            "  Or reinstall GhostRoll: pip install -e .\n"
            "  Note: QR codes are optional - the share URL will still be available in share.txt"
        ) from e
    except Exception as e:  # noqa: BLE001
        raise QrError(
            f"Failed to import qrcode package: {e}\n"
            "  Try: pip install --upgrade qrcode[pil]"
        ) from e

    out_path.parent.mkdir(parents=True, exist_ok=True)
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,  # High error correction: 30% error correction for maximum robustness on e-ink displays
        # HIGH provides 30% error correction, essential for e-ink displays where artifacts, ghosting, and imperfect rendering can occur
        # This makes the QR code more reliable even if some pixels are degraded during e-ink rendering
        box_size=12,  # Increased from 10 to 12 for larger initial QR code (better quality when resized)
        border=4,  # Increased border (quiet zone) to 4 modules for better scanning reliability
        # Larger border ensures phones can easily detect the QR code boundaries even with e-ink rendering artifacts
    )
    qr.add_data(data)
    qr.make(fit=True)
    # Generate high-quality QR code image with sharp edges for better phone scanning
    # Using RGB mode first, then convert to 1-bit for crisp black/white edges
    img = qr.make_image(fill_color="black", back_color="white")
    # Convert to 1-bit mode (monochrome) for optimal e-ink display and scanning
    img = img.convert("1")
    img.save(out_path)
    # Ensure file is fully written and synced to disk before returning
    # This is critical for e-ink display to pick up the QR code immediately
    try:
        import os
        fd = os.open(str(out_path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except Exception:
        # If sync fails, at least ensure the file handle is closed
        # The file should still be written, just not guaranteed synced
        pass


def render_qr_ascii(data: str) -> str:
    """
    Returns an ASCII QR code (useful for printing in terminal/logs).
    """
    try:
        import qrcode
    except ImportError as e:
        raise QrError(
            "QR code generation requires the 'qrcode' package.\n"
            "  Install with: pip install qrcode[pil]\n"
            "  Or reinstall GhostRoll: pip install -e .\n"
            "  Note: QR codes are optional - the share URL will still be available in share.txt"
        ) from e
    except Exception as e:  # noqa: BLE001
        raise QrError(
            f"Failed to import qrcode package: {e}\n"
            "  Try: pip install --upgrade qrcode[pil]"
        ) from e

    # Keep terminal output compact: no quiet-zone border.
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0)
    qr.add_data(data)
    qr.make(fit=True)
    # NOTE: qrcode's print_ascii writes to stdout; we emulate by using its internal matrix.
    # We pack two QR rows into one terminal line using half-block characters to cut height ~in half.
    m = qr.get_matrix()
    if not m:
        return ""
    lines: list[str] = []
    h = len(m)
    w = len(m[0])
    for y in range(0, h, 2):
        top = m[y]
        bottom = m[y + 1] if y + 1 < h else [False] * w
        line_chars: list[str] = []
        for x in range(w):
            t = bool(top[x])
            b = bool(bottom[x])
            if t and b:
                line_chars.append("█")
            elif t and not b:
                line_chars.append("▀")
            elif (not t) and b:
                line_chars.append("▄")
            else:
                line_chars.append(" ")
        lines.append("".join(line_chars))
    return "\n".join(lines)


