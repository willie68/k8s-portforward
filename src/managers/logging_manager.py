"""
Logging manager for port-forward events.
Runs in background and writes to log files configured in config.yaml.
"""

import logging
import logging.handlers
import threading
from pathlib import Path
from typing import Optional

from src.models.portforward_config import LoggingConfig


class LoggingManager:
    """
    Manages application logging to file.
    
    Logs are written asynchronously via QueueHandler to avoid blocking the UI.
    Events logged:
    - Port forward start
    - Port forward stop
    - Health check failures (with details)
    """

    def __init__(self, config: LoggingConfig) -> None:
        self.config = config
        self.logger: Optional[logging.Logger] = None
        self._setup_logging()

    def _setup_logging(self) -> None:
        """Initialize logger with rotating file handler in background thread."""
        if not self.config.enabled:
            return

        try:
            # Create log directory
            log_dir = Path(self.config.log_dir)
            log_dir.mkdir(parents=True, exist_ok=True)

            log_file = log_dir / self.config.log_file

            # Create logger
            self.logger = logging.getLogger("portforward")
            self.logger.setLevel(logging.DEBUG)

            # Remove existing handlers to avoid duplicates
            self.logger.handlers.clear()

            # Create rotating file handler (5 MB per file, keep 5 backups)
            handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=5 * 1024 * 1024,  # 5 MB
                backupCount=5,
                encoding="utf-8",
            )

            # Create formatter with timestamp, level, and message
            formatter = logging.Formatter(
                "%(asctime)s - %(levelname)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

        except Exception as e:
            print(f"Failed to setup logging: {e}")
            self.logger = None

    def log_forward_started(self, name: str, resource: str, port_mapping: str) -> None:
        """Log that a port-forward has started."""
        if not self.logger:
            return
        self.logger.info(
            f"Port-forward STARTED: {name} ({resource}) {port_mapping}"
        )

    def log_forward_stopped(self, name: str, reason: str = "User action") -> None:
        """Log that a port-forward has stopped."""
        if not self.logger:
            return
        self.logger.info(f"Port-forward STOPPED: {name} ({reason})")

    def log_health_check_failure(
        self,
        name: str,
        port: int,
        path: Optional[str],
        fail_count: int,
        error_detail: str = "",
        tls: bool = False,
    ) -> None:
        """
        Log that a health check has failed.
        
        Args:
            name: Forward name
            port: Local port being checked
            path: Health check path (None for gRPC)
            fail_count: Current fail count
            error_detail: Additional error information
            tls: Whether HTTPS/TLS is used
        """
        if not self.logger:
            return
        
        if path is None:
            # gRPC health check
            url = f"grpc://127.0.0.1:{port}"
        else:
            # HTTP/HTTPS health check
            scheme = "https" if tls else "http"
            url = f"{scheme}://127.0.0.1:{port}{path}"
        
        msg = f"Health check FAILED for {name}: {url} (failure #{fail_count})"
        if error_detail:
            msg += f" - {error_detail}"
        
        self.logger.warning(msg)

    def log_forward_restarting(self, name: str, reason: str = "Auto-restart") -> None:
        """Log that a port-forward is being restarted."""
        if not self.logger:
            return
        self.logger.info(f"Port-forward RESTARTING: {name} ({reason})")

    def log_forward_error(self, name: str, error_message: str) -> None:
        """Log an error for a port-forward."""
        if not self.logger:
            return
        self.logger.error(f"Port-forward ERROR ({name}): {error_message}")

    def shutdown(self) -> None:
        """Shutdown the logger and flush remaining messages."""
        if self.logger:
            for handler in self.logger.handlers:
                handler.close()
            self.logger.handlers.clear()
