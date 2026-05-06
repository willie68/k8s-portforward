"""
Kubernetes Port Forward Manager
Entry point.

Usage:
    python -m src.main                      # use default config location
    python -m src.main path/to/config.yaml  # use a custom config file
"""

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

# On Windows, set the AppUserModelID *before* creating QApplication so that
# the taskbar shows the app icon instead of the python.exe icon.
if sys.platform == "win32":
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
        "portforward.k8s.manager.1"
    )

from src.managers.config_manager import ConfigManager
from src.ui.app_icon import create_app_icon
from src.ui.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Kubernetes Port Forward Manager")
    app.setOrganizationName("portforward")
    app.setWindowIcon(create_app_icon())
    # Keep the app running when the main window is hidden to tray.
    app.setQuitOnLastWindowClosed(False)

    if len(sys.argv) > 1:
        config_path = Path(sys.argv[1])
    else:
        config_path = ConfigManager.default_config_path()

    config_manager = ConfigManager(config_path)

    window = MainWindow(config_manager)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
