"""Custom widget for visualizing health check progress with an animated ring."""

from typing import Optional

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget


class ProgressRingWidget(QWidget):
    """Small circular progress ring indicator."""
    
    HEALTH_CHECK_INTERVAL = 30  # seconds
    
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.last_health_check_at = 0.0
        self.has_health_check = False
        self.setMinimumSize(24, 24)
        self.setMaximumSize(24, 24)
    
    def set_health_check_state(
        self, last_health_check_at: float, has_health_check: bool
    ) -> None:
        """Update health check state and trigger repaint."""
        self.last_health_check_at = last_health_check_at
        self.has_health_check = has_health_check
        self.update()  # Request a repaint
    
    def _get_progress(self) -> float:
        """Calculate current progress (0.0 to 1.0)."""
        if not self.has_health_check:
            return 0.0
        
        # If we haven't had a check yet, show 1.0 (ready for first check)
        if abs(self.last_health_check_at) < 0.001:
            return 1.0
        
        import time
        now = time.time()
        elapsed = now - self.last_health_check_at
        
        # If more than HEALTH_CHECK_INTERVAL has passed, show full ring
        if elapsed >= self.HEALTH_CHECK_INTERVAL:
            return 1.0
        
        return elapsed / self.HEALTH_CHECK_INTERVAL
    
    def paintEvent(self, event: QPaintEvent) -> None:
        """Paint the progress ring."""
        if not self.has_health_check:
            return
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        rect = self.rect()
        center_x = rect.width() / 2
        center_y = rect.height() / 2
        radius = rect.width() / 2 - 2
        
        # Background ring (light gray)
        bg_pen = QPen(QColor("#E0E0E0"), 1.5)
        bg_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(bg_pen)
        painter.drawEllipse(int(center_x - radius), int(center_y - radius), 
                           int(2 * radius), int(2 * radius))
        
        # Progress ring (green -> light blue, solid arc)
        progress = self._get_progress()
        if progress > 0:
            progress_color = self._progress_color(progress)
            fg_pen = QPen(progress_color, 1.5)
            fg_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(fg_pen)
            
            # Draw arc: start at top (90°) and go clockwise
            start_angle = 90 * 16
            span_angle = int(-progress * 360 * 16)
            painter.drawArc(
                int(center_x - radius),
                int(center_y - radius),
                int(2 * radius),
                int(2 * radius),
                start_angle,
                span_angle,
            )
        
        painter.end()
    
    def _progress_color(self, progress: float) -> QColor:
        """Return a color based on progress: green -> light blue."""
        # Green (0%) to Light Blue (100%)
        t = progress  # 0.0 to 1.0
        r = int(30 + (173 - 30) * t)
        g = int(138 + (216 - 138) * t)
        b = int(30 + (230 - 30) * t)
        return QColor(r, g, b)


class HealthCheckProgressWidget(QWidget):
    """
    Displays health check status side-by-side with an animated progress ring.
    
    Layout: [Ring] [Status Text]
    
    - Ring fills from green (just checked) to light blue (ready for next check)
    - Shows "-" if no health check is configured
    - Shows "OK" or "FAIL (n)" when configured
    """
    
    HEALTH_CHECK_INTERVAL = 30  # seconds
    
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.health_status = "-"
        self.last_health_check_at = 0.0
        self.has_health_check_path = False
        
        # Create layout
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)
        
        # Ring widget
        self._ring = ProgressRingWidget()
        layout.addWidget(self._ring, alignment=Qt.AlignmentFlag.AlignCenter)
        
        # Status text label
        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label, alignment=Qt.AlignmentFlag.AlignCenter)
        
        layout.addStretch()
    
    def set_health_status(
        self,
        health_status: str,
        last_health_check_at: float,
        has_health_check_path: bool,
    ) -> None:
        """Update the health status and timing information."""
        self.health_status = health_status
        self.last_health_check_at = last_health_check_at
        self.has_health_check_path = has_health_check_path
        
        # Update ring state
        self._ring.set_health_check_state(last_health_check_at, has_health_check_path)
        
        # Update text label
        if self.health_status == "-":
            text = "-"
            text_color = QColor("#888888")
        elif self.health_status == "OK":
            text = "OK"
            text_color = QColor("#1E8A1E")
        elif self.health_status.startswith("FAIL"):
            text = self.health_status
            text_color = QColor("#CC0000")
        else:
            text = self.health_status
            text_color = QColor("#888888")
        
        self._label.setText(text)
        self._label.setStyleSheet(f"color: {text_color.name()}; font-weight: bold;")
    
    def sizeHint(self) -> QSize:
        """Return preferred size for table cell."""
        return QSize(100, 32)
    
    def minimumSizeHint(self) -> QSize:
        """Return minimum size for table cell."""
        return QSize(80, 24)
