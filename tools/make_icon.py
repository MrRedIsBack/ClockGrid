"""Draw the ClockGrid icon and save it as clockgrid/assets/clockgrid.ico (and a PNG).

Run from the project root:  .venv\\Scripts\\python tools\\make_icon.py
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen

SIZES = [16, 24, 32, 48, 64, 128, 256]
ASSETS = Path(__file__).resolve().parent.parent / "clockgrid" / "assets"


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Rounded square background
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#2f6fe4"))
    radius = size * 0.22
    p.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)

    # Progress ring: faint track plus a 70% arc from the top
    thickness = max(2.0, size * 0.13)
    inset = size * 0.2 + thickness / 2
    rect = QRectF(inset, inset, size - 2 * inset, size - 2 * inset)
    pen = QPen(QColor(255, 255, 255, 80), thickness)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.drawArc(rect, 0, 360 * 16)
    pen.setColor(QColor("white"))
    p.setPen(pen)
    p.drawArc(rect, 90 * 16, -int(0.7 * 360 * 16))
    p.end()
    return img


def png_bytes(img: QImage) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data)


def write_ico(path: Path, images: list[QImage]) -> None:
    """ICO file with PNG-compressed entries (supported since Windows Vista)."""
    blobs = [png_bytes(img) for img in images]
    header = struct.pack("<HHH", 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    entries = b""
    for img, blob in zip(images, blobs):
        w = img.width() if img.width() < 256 else 0  # 0 means 256
        entries += struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    path.write_bytes(header + entries + b"".join(blobs))


def main() -> None:
    app = QGuiApplication(sys.argv)  # noqa: F841 (needed for painting)
    ASSETS.mkdir(parents=True, exist_ok=True)
    images = [draw(s) for s in SIZES]
    write_ico(ASSETS / "clockgrid.ico", images)
    images[-1].save(str(ASSETS / "clockgrid.png"))
    print(f"Wrote {ASSETS / 'clockgrid.ico'}")


if __name__ == "__main__":
    main()
