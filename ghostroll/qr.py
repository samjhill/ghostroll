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
    except Exception as e:  # noqa: BLE001
        raise QrError(
            "QR support requires the 'qrcode' package. Install it (pip install -e .) and retry."
        ) from e

    out_path.parent.mkdir(parents=True, exist_ok=True)
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(out_path)


def render_qr_ascii(data: str) -> str:
    """
    Returns an ASCII QR code (useful for printing in terminal/logs).
    """
    try:
        import qrcode
    except Exception as e:  # noqa: BLE001
        raise QrError(
            "QR support requires the 'qrcode' package. Install it (pip install -e .) and retry."
        ) from e

    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=1)
    qr.add_data(data)
    qr.make(fit=True)
    # NOTE: qrcode's print_ascii writes to stdout; we emulate by using its internal matrix.
    # We use a simple block representation.
    m = qr.get_matrix()
    lines: list[str] = []
    for row in m:
        lines.append("".join("██" if cell else "  " for cell in row))
    return "\n".join(lines)


