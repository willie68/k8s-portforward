"""Live log viewer widget for displaying port-forward events."""

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QTextCursor
from PyQt6.QtWidgets import QMainWindow, QPlainTextEdit, QVBoxLayout, QWidget


class _LogFileMonitor(QObject):
    """Monitors log file for changes and emits signal when new content is available."""
    
    new_content = pyqtSignal(str)  # Emits new log lines
    
    def __init__(self, log_file: Path, read_initial: bool = False) -> None:
        super().__init__()
        self.log_file = log_file
        self.last_size = 0
        
        # Setup timer to check for file changes every 500ms
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._check_file_changes)
        self.timer.start(500)
        
        # Read initial content if requested (after signal is connected)
        if read_initial:
            self._read_initial_content()
    
    def _read_initial_content(self) -> None:
        """Read the entire log file initially."""
        if self.log_file.exists():
            try:
                with open(self.log_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    self.last_size = len(content)
                    if content:
                        self.new_content.emit(content)
            except Exception:
                pass
    
    def _check_file_changes(self) -> None:
        """Check if log file has new content and emit signal."""
        if not self.log_file.exists():
            return
        
        try:
            current_size = self.log_file.stat().st_size
            
            # If file got smaller (rotated), read all content
            if current_size < self.last_size:
                self._read_initial_content()
                return
            
            # If file got bigger, read new content
            if current_size > self.last_size:
                with open(self.log_file, 'r', encoding='utf-8') as f:
                    f.seek(self.last_size)
                    new_content = f.read()
                    self.last_size = current_size
                    if new_content:
                        self.new_content.emit(new_content)
        except Exception:
            pass
    
    def stop(self) -> None:
        """Stop monitoring."""
        self.timer.stop()


class LogViewerWindow(QMainWindow):
    """Standalone window for viewing live logs."""
    
    def __init__(self, log_file: Optional[Path] = None, parent=None) -> None:
        super().__init__(parent)
        self.log_file = log_file
        self.monitor: Optional[_LogFileMonitor] = None
        
        self.setWindowTitle("Port Forward - Live Log Viewer")
        self.resize(QSize(900, 500))
        
        # Create central widget with text display
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(4, 4, 4, 4)
        
        # Read-only text display
        self.text_display = QPlainTextEdit()
        self.text_display.setReadOnly(True)
        
        # Use monospace font for better log readability
        font = QFont("Courier New", 9)
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        self.text_display.setFont(font)
        
        layout.addWidget(self.text_display)
        
        # Start monitoring if log file is provided
        if self.log_file and self.log_file.exists():
            self.monitor = _LogFileMonitor(self.log_file, read_initial=False)
            # Connect signal BEFORE reading initial content
            self.monitor.new_content.connect(self._on_new_content)
            # Now read and display the entire log file
            self.monitor._read_initial_content()
    
    def _on_new_content(self, content: str) -> None:
        """Append new content to text display and scroll to bottom."""
        # For initial content load, just set it
        if not self.text_display.toPlainText():
            self.text_display.setPlainText(content)
        else:
            # For subsequent updates, append new content
            cursor = self.text_display.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText(content)
            
            # Auto-scroll to bottom
            self.text_display.setTextCursor(cursor)
            self.text_display.ensureCursorVisible()
    
    def closeEvent(self, event) -> None:
        """Clean up monitor on close."""
        if self.monitor:
            self.monitor.stop()
        super().closeEvent(event)
