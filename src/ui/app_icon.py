"""Application icon – generated via QPainter, no external file needed."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)


def create_app_icon() -> QIcon:
    """Return a QIcon with several sizes of the port-forward logo."""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(_render(size))
    return icon


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_BG       = QColor("#326CE5")   # Kubernetes blue
_BG_DARK  = QColor("#1A4AAF")   # slightly darker ring
_FG       = QColor("#FFFFFF")   # white elements
_ACCENT   = QColor("#E8F0FE")   # light-blue accent


def _render(size: int) -> QPixmap:
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)

    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    s = size
    m = s * 0.04   # margin

    # --- Background circle ---
    p.setPen(QPen(_BG_DARK, s * 0.04))
    p.setBrush(QBrush(_BG))
    p.drawEllipse(int(m), int(m), int(s - 2 * m), int(s - 2 * m))

    # --- Two port boxes ---
    box_w  = s * 0.20
    box_h  = s * 0.28
    box_r  = s * 0.06   # corner radius
    y_box  = s * 0.36   # vertical centre of boxes
    x_left  = s * 0.16
    x_right = s * 0.64

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(_FG))
    for bx in (x_left, x_right):
        p.drawRoundedRect(
            int(bx), int(y_box - box_h / 2),
            int(box_w), int(box_h),
            box_r, box_r,
        )

    # Small port-plug dots on left box (right edge) and right box (left edge)
    dot_r = s * 0.045
    p.setBrush(QBrush(_BG))
    p.setPen(Qt.PenStyle.NoPen)
    # left box: two dots on right side
    for dy in (-0.08, 0.08):
        p.drawEllipse(
            int(x_left + box_w - dot_r * 0.6),
            int(y_box + dy * s - dot_r),
            int(dot_r * 2), int(dot_r * 2),
        )
    # right box: two dots on left side
    for dy in (-0.08, 0.08):
        p.drawEllipse(
            int(x_right - dot_r * 1.4),
            int(y_box + dy * s - dot_r),
            int(dot_r * 2), int(dot_r * 2),
        )

    # --- Arrow between the boxes ---
    arrow_y   = s * 0.36
    arrow_x1  = x_left + box_w + s * 0.03
    arrow_x2  = x_right - s * 0.03
    shaft_h   = s * 0.055
    head_w    = s * 0.12
    head_h    = s * 0.18

    path = QPainterPath()
    # shaft
    path.addRect(
        arrow_x1,
        arrow_y - shaft_h / 2,
        arrow_x2 - arrow_x1 - head_w,
        shaft_h,
    )
    # arrowhead
    tip_x = arrow_x2
    tip_y = arrow_y
    base_x = arrow_x2 - head_w
    path.moveTo(tip_x, tip_y)
    path.lineTo(base_x, tip_y - head_h / 2)
    path.lineTo(base_x, tip_y + head_h / 2)
    path.closeSubpath()

    p.setBrush(QBrush(_ACCENT))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPath(path)

    p.end()
    return px
