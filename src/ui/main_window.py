from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import QObject, QSettings, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QCloseEvent, QColor, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QStyle,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.managers.config_manager import ConfigManager, ProfileManager
from src.managers.logging_manager import LoggingManager
from src.managers.process_manager import ForwardState, ForwardStatus, ProcessManager
from src.models.portforward_config import AppConfig, ForwardEntry
from src.ui.app_icon import create_app_icon
from src.ui.forward_dialog import ForwardDialog
from src.ui.log_viewer_widget import LogViewerWindow

# ---------------------------------------------------------------------------
# Column indices
# ---------------------------------------------------------------------------
COL_ENABLED = 0
COL_NAME = 1
COL_RESOURCE = 2
COL_LOCAL_PORT = 3
COL_REMOTE_PORT = 4
COL_CONTEXT = 5
COL_STATUS = 6
COL_HEALTH = 7
COL_RESTARTS = 8
COL_LAST_EVENT = 9

COLUMN_LABELS = [
    "",           # checkbox
    "Name",
    "Resource",
    "Local Port",
    "Remote Port",
    "Context",
    "Status",
    "Health",
    "Restarts",
    "Last Event",
]

# ---------------------------------------------------------------------------
# Status → foreground colour mapping
# ---------------------------------------------------------------------------
_STATUS_COLOR: dict[ForwardStatus, QColor] = {
    ForwardStatus.STOPPED:    QColor("#888888"),
    ForwardStatus.STARTING:   QColor("#E07B00"),
    ForwardStatus.RUNNING:    QColor("#1E8A1E"),
    ForwardStatus.RESTARTING: QColor("#E07B00"),
    ForwardStatus.ERROR:      QColor("#CC0000"),
}


# 2-state sort cycle for current column: Ascending → Descending → (resets to Name Ascending)
_SORT_NEXT: dict = {
    None: Qt.SortOrder.AscendingOrder,
    Qt.SortOrder.AscendingOrder: Qt.SortOrder.DescendingOrder,
    Qt.SortOrder.DescendingOrder: None,
}

# Sort key per column (entry, state) → comparable value
def _sort_key(col: int):
    def key(pair):
        entry, state = pair
        if col == COL_NAME:        return entry.name.lower()
        if col == COL_RESOURCE:    return entry.resource.lower()
        if col == COL_LOCAL_PORT:  return entry.local_port
        if col == COL_REMOTE_PORT: return entry.remote_port
        if col == COL_CONTEXT:     return (entry.context or "").lower()
        if col == COL_STATUS:      return (state.status.value if state else "")
        if col == COL_RESTARTS:    return (state.restart_count if state else 0)
        return ""
    return key


# ---------------------------------------------------------------------------
# Thread-safe signal bridge
# ---------------------------------------------------------------------------
class _StatusSignal(QObject):
    changed = pyqtSignal(str)


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self, config_manager: ConfigManager) -> None:
        super().__init__()
        self._config_manager = config_manager
        self._profile_manager = ProfileManager(config_manager.config_path)
        self._config: Optional[AppConfig] = None
        self._logger_manager: Optional[LoggingManager] = None
        self._log_viewer_window: Optional[LogViewerWindow] = None
        self.setWindowIcon(create_app_icon())
        # Signal bridge: emitted from the monitor thread, consumed on the UI thread.
        self._signal = _StatusSignal()
        self._signal.changed.connect(self._refresh_status_columns)

        self._process_manager = ProcessManager(
            on_status_change=lambda name: self._signal.changed.emit(name)
        )

        self._setup_ui()
        self._setup_tray()
        self._restore_geometry()

        # Sorted display order: list of ForwardEntry in current visual order.
        # Enabled services appear first, then sorted by current sort column (default: Name asc).
        self._display_entries: List[ForwardEntry] = []
        self._sort_col: int = COL_NAME
        self._sort_order: Qt.SortOrder = Qt.SortOrder.AscendingOrder

        self._load_config()

        # Periodic UI refresh to keep status columns current.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(2_000)
        self._refresh_timer.timeout.connect(self._refresh_status_columns)
        self._refresh_timer.start()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        self.setWindowTitle("Kubernetes Port Forward Manager")
        self.setMinimumSize(950, 420)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 4)

        # --- Single combined toolbar + profiles + filter row ---
        toolbar = QHBoxLayout()

        def _icon_btn(pixmap: QStyle.StandardPixmap, tip: str) -> QPushButton:
            btn = QPushButton()
            btn.setIcon(self.style().standardIcon(pixmap))
            btn.setToolTip(tip)
            btn.setFixedSize(32, 32)
            return btn

        btn_reload = _icon_btn(
            QStyle.StandardPixmap.SP_BrowserReload,
            "Konfiguration neu laden (stoppt alle aktiven Forwards)",
        )
        btn_reload.clicked.connect(self._on_reload_config)
        toolbar.addWidget(btn_reload)

        btn_add = _icon_btn(
            QStyle.StandardPixmap.SP_FileDialogNewFolder,
            "Neuen Port Forward anlegen",
        )
        btn_add.clicked.connect(self._on_add_forward)
        toolbar.addWidget(btn_add)

        btn_edit = _icon_btn(
            QStyle.StandardPixmap.SP_FileDialogDetailedView,
            "Markierten Port Forward bearbeiten (auch Doppelklick)",
        )
        btn_edit.clicked.connect(self._on_edit_forward)
        toolbar.addWidget(btn_edit)

        btn_delete = _icon_btn(
            QStyle.StandardPixmap.SP_DialogDiscardButton,
            "Markierten Port Forward loeschen",
        )
        btn_delete.clicked.connect(self._on_delete_forward)
        toolbar.addWidget(btn_delete)

        btn_open = _icon_btn(
            QStyle.StandardPixmap.SP_FileIcon,
            "Konfigurationsdatei im Editor öffnen",
        )
        btn_open.clicked.connect(self._on_open_config)
        toolbar.addWidget(btn_open)

        btn_choose = _icon_btn(
            QStyle.StandardPixmap.SP_DirOpenIcon,
            "Andere Konfigurationsdatei auswählen…",
        )
        btn_choose.clicked.connect(self._on_choose_config)
        toolbar.addWidget(btn_choose)

        toolbar.addSpacing(12)

        toolbar.addWidget(QLabel("Profil:"))
        self._profile_combo = QComboBox()
        self._profile_combo.setMinimumWidth(160)
        self._profile_combo.setToolTip("Gespeichertes Profil auswählen und anwenden")
        self._profile_combo.currentIndexChanged.connect(self._on_profile_selected)
        toolbar.addWidget(self._profile_combo)

        btn_save_profile = _icon_btn(
            QStyle.StandardPixmap.SP_DialogSaveButton,
            "Aktuelle Selektion als neues Profil speichern",
        )
        btn_save_profile.clicked.connect(self._on_save_profile)
        toolbar.addWidget(btn_save_profile)

        btn_delete_profile = _icon_btn(
            QStyle.StandardPixmap.SP_TrashIcon,
            "Ausgewähltes Profil löschen",
        )
        btn_delete_profile.clicked.connect(self._on_delete_profile)
        toolbar.addWidget(btn_delete_profile)

        toolbar.addSpacing(12)

        toolbar.addWidget(QLabel("Filter:"))
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Name filtern…")
        self._search_box.setClearButtonEnabled(True)
        self._search_box.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self._search_box, stretch=1)

        toolbar.addSpacing(12)

        btn_log = _icon_btn(
            QStyle.StandardPixmap.SP_FileIcon,
            "Live-Log anzeigen",
        )
        btn_log.clicked.connect(self._on_show_log)
        toolbar.addWidget(btn_log)

        toolbar.addSpacing(12)

        btn_stop_all = _icon_btn(
            QStyle.StandardPixmap.SP_MediaStop,
            "Alle aktiven Forwards deaktivieren",
        )
        btn_stop_all.clicked.connect(self._on_stop_all)
        toolbar.addWidget(btn_stop_all)

        btn_quit = _icon_btn(
            QStyle.StandardPixmap.SP_TitleBarCloseButton,
            "Alle Forwards stoppen und beenden",
        )
        btn_quit.clicked.connect(self._quit)
        toolbar.addWidget(btn_quit)

        layout.addLayout(toolbar)

        # --- Forward list table ---
        self._table = QTableWidget()
        self._table.setColumnCount(len(COLUMN_LABELS))
        self._table.setHorizontalHeaderLabels(COLUMN_LABELS)

        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(COL_RESOURCE, QHeaderView.ResizeMode.Stretch)

        self._table.setColumnWidth(COL_ENABLED,     32)
        self._table.setColumnWidth(COL_LOCAL_PORT,  85)
        self._table.setColumnWidth(COL_REMOTE_PORT, 95)
        self._table.setColumnWidth(COL_CONTEXT,     100)
        self._table.setColumnWidth(COL_STATUS,      95)
        self._table.setColumnWidth(COL_HEALTH,      80)
        self._table.setColumnWidth(COL_RESTARTS,    65)
        self._table.setColumnWidth(COL_LAST_EVENT,  80)

        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setWordWrap(False)
        self._table.setStyleSheet(
            "QTableWidget::item:hover { background-color: #d0d0d0; } "
            "QTableWidget::item:selected { background-color: #e0e0e0; }"
        )

        hh.setSortIndicatorShown(True)
        hh.setSortIndicator(COL_NAME, Qt.SortOrder.AscendingOrder)  # default: Name ascending
        hh.sectionClicked.connect(self._on_header_clicked)

        self._table.itemChanged.connect(self._on_item_changed)
        self._table.itemDoubleClicked.connect(self._on_table_double_clicked)
        layout.addWidget(self._table)

        # --- Status bar ---
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Ready")

    def _setup_tray(self) -> None:
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(create_app_icon())
        self._tray.setToolTip("Kubernetes Port Forward Manager")

        menu = QMenu()
        act_show = QAction("Show", self)
        act_show.triggered.connect(self._restore_window)
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(self._quit)
        menu.addAction(act_show)
        menu.addSeparator()
        menu.addAction(act_quit)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    # ------------------------------------------------------------------
    # Config management
    # ------------------------------------------------------------------

    def _load_config(self) -> None:
        # Stop all active forwards before replacing the config.
        if self._config:
            for entry in self._config.forwards:
                self._process_manager.set_desired(entry, False)

        try:
            config = self._config_manager.load()
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Configuration Error",
                f"Failed to load configuration:\n\n{exc}",
            )
            return

        self._config = config

        # Initialize logging manager
        if self._logger_manager:
            self._logger_manager.shutdown()
        self._logger_manager = LoggingManager(config.logging)
        self._process_manager.set_logger(self._logger_manager)

        for entry in config.forwards:
            self._process_manager.register(entry)

        self._rebuild_table()
        self._reload_profiles()
        self._status_bar.showMessage(
            f"Loaded {len(config.forwards)} forward(s) from {self._config_manager.config_path}"
        )

    def _on_reload_config(self) -> None:
        self._load_config()

    def _on_open_config(self) -> None:
        try:
            self._config_manager.open_in_editor()
        except Exception as exc:
            QMessageBox.warning(self, "Cannot Open File", str(exc))

    def _on_choose_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Config File",
            str(self._config_manager.config_path.parent),
            "YAML files (*.yaml *.yml);;All files (*)",
        )
        if path:
            from pathlib import Path

            self._config_manager.config_path = Path(path)
            self._load_config()

    def _on_add_forward(self) -> None:
        """Open the ForwardEntry dialog and add the new entry to the config."""
        if not self._config:
            return
        existing_names = [e.name for e in self._config.forwards]
        dlg = ForwardDialog(parent=self, existing_names=existing_names)
        if dlg.exec() != ForwardDialog.DialogCode.Accepted:
            return
        entry = dlg.result_entry()
        self._config.forwards.append(entry)
        self._config_manager.save(self._config)
        self._process_manager.register(entry)
        self._rebuild_table()
        self._status_bar.showMessage(f'Port Forward "{entry.name}" hinzugefuegt.')

    def _on_table_double_clicked(self, item: QTableWidgetItem) -> None:
        """Open edit dialog on row double-click (except checkbox column)."""
        if item.column() == COL_ENABLED:
            return
        self._on_edit_forward()

    def _on_edit_forward(self) -> None:
        """Open ForwardDialog pre-filled with the currently selected entry."""
        if not self._config:
            return
        selected = self._table.selectedItems()
        if not selected:
            QMessageBox.information(self, "Bearbeiten", "Bitte zuerst einen Eintrag auswählen.")
            return
        row = self._table.row(selected[0])
        if row < 0 or row >= len(self._display_entries):
            return
        entry = self._display_entries[row]

        existing_names = [e.name for e in self._config.forwards]
        dlg = ForwardDialog(parent=self, entry=entry, existing_names=existing_names)
        if dlg.exec() != ForwardDialog.DialogCode.Accepted:
            return

        updated = dlg.result_entry()
        old_name = entry.name

        # Stop the forward if it is currently running before replacing it.
        was_running = False
        state = self._process_manager.get_state(old_name)
        if state and state.desired_running:
            was_running = True
            self._process_manager.set_desired(entry, False)

        # Replace in the config list in-place to keep ordering.
        idx = next(i for i, e in enumerate(self._config.forwards) if e.name == old_name)
        self._config.forwards[idx] = updated
        self._config_manager.save(self._config)
        self._process_manager.register(updated)

        # Restart if it was running before the edit.
        if was_running:
            self._process_manager.set_desired(updated, True)

        self._rebuild_table()
        self._status_bar.showMessage(f'Port Forward "{updated.name}" gespeichert.')

    def _on_delete_forward(self) -> None:
        """Delete the selected entry after confirmation."""
        if not self._config:
            return
        selected = self._table.selectedItems()
        if not selected:
            QMessageBox.information(self, "Loeschen", "Bitte zuerst einen Eintrag auswaehlen.")
            return
        row = self._table.row(selected[0])
        if row < 0 or row >= len(self._display_entries):
            return
        entry = self._display_entries[row]

        reply = QMessageBox.question(
            self,
            "Eintrag loeschen",
            f'Port Forward "{entry.name}" wirklich loeschen?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Stop the forward if it is running.
        state = self._process_manager.get_state(entry.name)
        if state and state.desired_running:
            self._process_manager.set_desired(entry, False)

        self._config.forwards = [e for e in self._config.forwards if e.name != entry.name]
        self._config_manager.save(self._config)
        self._rebuild_table()
        self._status_bar.showMessage(f'Port Forward "{entry.name}" geloescht.')

    # ------------------------------------------------------------------
    # Table management
    # ------------------------------------------------------------------

    def _rebuild_table(self) -> None:
        """Full table rebuild – used after config load or sort change."""
        if not self._config:
            return
        self._apply_sort()  # sets self._display_entries
        self._table.blockSignals(True)
        self._table.setRowCount(len(self._display_entries))
        for row, entry in enumerate(self._display_entries):
            self._populate_row(row, entry)
        self._table.blockSignals(False)
        self._apply_filter(self._search_box.text())

    def _apply_sort(self) -> None:
        """Recompute _display_entries according to current sort state.
        
        Enabled (desired_running=True) services appear first, then disabled.
        Within each group, services are sorted by current sort column.
        Default is Name in ascending order.
        """
        if not self._config:
            return
        
        pairs = [
            (entry, self._process_manager.get_state(entry.name))
            for entry in self._config.forwards
        ]
        
        # Group by enabled/disabled
        enabled = [(e, s) for e, s in pairs if s and s.desired_running]
        disabled = [(e, s) for e, s in pairs if not s or not s.desired_running]
        
        # Sort each group by current sort column
        sort_func = _sort_key(self._sort_col)
        for group in [enabled, disabled]:
            group.sort(
                key=sort_func,
                reverse=(self._sort_order == Qt.SortOrder.DescendingOrder),
            )
        
        self._display_entries = [e for e, _ in enabled + disabled]

    def _on_header_clicked(self, col: int) -> None:
        """Cycle sort: col asc → col desc → Name asc (per column)."""
        if col == COL_ENABLED:  # checkbox column: not sortable
            return
        if col == self._sort_col:
            self._sort_order = _SORT_NEXT[self._sort_order]
            if self._sort_order is None:
                # Reset to Name ascending instead of unsorted
                self._sort_col = COL_NAME
                self._sort_order = Qt.SortOrder.AscendingOrder
        else:
            self._sort_col = col
            self._sort_order = Qt.SortOrder.AscendingOrder

        hh = self._table.horizontalHeader()
        hh.setSortIndicator(self._sort_col, self._sort_order)

        self._rebuild_table()

    def _apply_filter(self, text: str) -> None:
        """Show only rows whose name contains *text* (case-insensitive)."""
        needle = text.strip().lower()
        for row in range(self._table.rowCount()):
            name_item = self._table.item(row, COL_NAME)
            name = name_item.text().lower() if name_item else ""
            self._table.setRowHidden(row, bool(needle and needle not in name))

    def _populate_row(self, row: int, entry: ForwardEntry) -> None:
        """Write all cells for *row*."""
        state = self._process_manager.get_state(entry.name)

        # -- Checkbox --
        chk = QTableWidgetItem()
        chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        checked = state is not None and state.desired_running
        chk.setCheckState(
            Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        )
        self._table.setItem(row, COL_ENABLED, chk)

        # -- Static data columns --
        for col, text in [
            (COL_NAME,        entry.name),
            (COL_RESOURCE,    entry.resource),
            (COL_LOCAL_PORT,  str(entry.local_port)),
            (COL_REMOTE_PORT, str(entry.remote_port)),
            (COL_CONTEXT,     entry.context or "-"),
        ]:
            item = QTableWidgetItem(text)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self._table.setItem(row, col, item)

        # -- Dynamic status columns --
        self._write_status_cells(row, state)

    def _write_status_cells(
        self, row: int, state: Optional[ForwardState]
    ) -> None:
        status = state.status if state else ForwardStatus.STOPPED
        restarts = str(state.restart_count) if state else "0"
        last_event = state.last_event if state else "-"
        error_tip = (state.error_message if state and state.error_message else "")
        health_text = state.health_status if state else "-"

        # Status cell
        status_item = QTableWidgetItem(status.value)
        status_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        color = _STATUS_COLOR.get(status, QColor("#888888"))
        status_item.setForeground(color)
        bold = QFont()
        bold.setBold(status == ForwardStatus.RUNNING)
        status_item.setFont(bold)
        if error_tip:
            status_item.setToolTip(error_tip)
        self._table.setItem(row, COL_STATUS, status_item)

        # Health cell
        health_item = QTableWidgetItem(health_text)
        health_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        health_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if health_text == "OK":
            health_item.setForeground(QColor("#1E8A1E"))
        elif health_text.startswith("FAIL"):
            health_item.setForeground(QColor("#CC0000"))
        else:
            health_item.setForeground(QColor("#888888"))
        self._table.setItem(row, COL_HEALTH, health_item)

        # Restarts cell
        restart_item = QTableWidgetItem(restarts)
        restart_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        restart_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table.setItem(row, COL_RESTARTS, restart_item)

        # Last event cell
        event_item = QTableWidgetItem(last_event)
        event_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        self._table.setItem(row, COL_LAST_EVENT, event_item)

    def _refresh_status_columns(self) -> None:
        """Light-weight refresh – only updates the dynamic status columns."""
        if not self._config:
            return
        self._table.blockSignals(True)
        for row, entry in enumerate(self._display_entries):
            state = self._process_manager.get_state(entry.name)
            self._write_status_cells(row, state)
        self._table.blockSignals(False)

    # ------------------------------------------------------------------
    # User interaction
    # ------------------------------------------------------------------

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != COL_ENABLED:
            return
        if not self._config:
            return
        row = item.row()
        if row < 0 or row >= len(self._display_entries):
            return

        entry = self._display_entries[row]
        start = item.checkState() == Qt.CheckState.Checked
        
        # Check for port conflicts when trying to activate a forward
        if start:
            conflict_info = self._check_port_conflict(entry)
            if conflict_info:
                new_port = self._show_port_conflict_dialog(entry, conflict_info)
                if new_port and new_port != entry.local_port:
                    # Update the entry with the new port and save the config
                    entry.local_port = new_port
                    if self._config:
                        self._config_manager.save(self._config)
                        # Re-register with the process manager to use updated entry
                        self._process_manager.register(entry)
                elif new_port is None:
                    # User cancelled – uncheck the box
                    self._table.blockSignals(True)
                    item.setCheckState(Qt.CheckState.Unchecked)
                    self._table.blockSignals(False)
                    return
        
        self._process_manager.set_desired(entry, start)
        self._rebuild_table()  # Re-sort after status change

    def _check_port_conflict(self, entry: ForwardEntry) -> Optional[dict]:
        """
        Check if the given entry's local port conflicts with active (running) forwards.
        
        Only checks against truly active forwards (desired_running=True).
        
        Returns a dict with conflict info or None if no conflicts.
        """
        if not self._config:
            return None
        
        conflicts = []
        
        # Check only for other ACTIVE entries with the same local port
        for other in self._config.forwards:
            if other.name == entry.name:
                continue
            if other.local_port == entry.local_port:
                state = self._process_manager.get_state(other.name)
                # Only report active forwards
                if state and state.desired_running:
                    conflicts.append({
                        "name": other.name,
                        "local_port": other.local_port,
                        "is_active": True,
                    })
        
        return {"conflicts": conflicts} if conflicts else None

    def _show_port_conflict_dialog(self, entry: ForwardEntry, conflict_info: dict) -> Optional[int]:
        """
        Show a dialog when a port conflict is detected.
        Returns the new port chosen by the user, or None if cancelled.
        """
        conflicts = conflict_info["conflicts"]
        
        # Build message
        conflict_lines = []
        for c in conflicts:
            status = "aktiv" if c["is_active"] else "definiert"
            conflict_lines.append(f"  • {c['name']} auf Port {c['local_port']} ({status})")
        
        message = (
            f"Port {entry.local_port} ist bereits in Verwendung:\n\n"
            + "\n".join(conflict_lines) + "\n\n"
            "Bitte wählen Sie einen anderen Port oder brechen Sie ab."
        )
        
        # Find a suggested free port (next available)
        suggested_port = self._find_free_port(entry.local_port)
        
        while True:
            port_str, ok = QInputDialog.getText(
                self,
                "Port-Konflikt erkannt",
                f"Neuer lokaler Port (aktuelle: {entry.local_port}):\n\n{message}",
                text=str(suggested_port)
            )
            
            if not ok:
                return None
            
            try:
                new_port = int(port_str.strip())
                if not (1 <= new_port <= 65535):
                    QMessageBox.warning(
                        self,
                        "Ungültige Portnummer",
                        f"Port {new_port} ist außerhalb des gültigen Bereichs (1-65535)."
                    )
                    continue
                
                # Check if the new port also has conflicts
                if self._port_is_in_use(new_port, exclude_entry=entry):
                    QMessageBox.warning(
                        self,
                        "Port noch in Verwendung",
                        f"Port {new_port} ist ebenfalls bereits in Verwendung. Bitte wählen Sie einen anderen."
                    )
                    suggested_port = new_port + 1
                    continue
                
                return new_port
                
            except ValueError:
                QMessageBox.warning(
                    self,
                    "Ungültige Eingabe",
                    "Bitte geben Sie eine gültige Portnummer ein."
                )
                continue

    def _port_is_in_use(self, port: int, exclude_entry: Optional[ForwardEntry] = None) -> bool:
        """Check if a port is already used by another entry in the config."""
        if not self._config:
            return False
        for entry in self._config.forwards:
            if exclude_entry and entry.name == exclude_entry.name:
                continue
            if entry.local_port == port:
                return True
        return False

    def _find_free_port(self, start_port: int) -> int:
        """Find the next available port starting from start_port + 1."""
        candidate = start_port + 1
        max_attempts = 1000
        for _ in range(max_attempts):
            if not self._port_is_in_use(candidate):
                return candidate
            candidate += 1
        return candidate

    def _on_show_log(self) -> None:
        """Open or bring to front the log viewer window."""
        if self._logger_manager is None or self._logger_manager.logger is None:
            QMessageBox.warning(
                self,
                "Logging nicht aktiviert",
                "Logging wurde in der Konfiguration nicht aktiviert.",
            )
            return
        
        # Get log file path from logger
        log_handlers = self._logger_manager.logger.handlers
        if not log_handlers:
            return
        
        log_file = None
        for handler in log_handlers:
            if hasattr(handler, 'baseFilename'):
                log_file = Path(handler.baseFilename)
                break
        
        if not log_file:
            return
        
        if self._log_viewer_window is None or not self._log_viewer_window.isVisible():
            self._log_viewer_window = LogViewerWindow(log_file, parent=self)
            self._log_viewer_window.show()
        else:
            self._log_viewer_window.activateWindow()
            self._log_viewer_window.raise_()

    def _on_stop_all(self) -> None:
        """Uncheck and stop all currently active forwards."""
        if not self._config:
            return
        self._table.blockSignals(True)
        for row, entry in enumerate(self._display_entries):
            state = self._process_manager.get_state(entry.name)
            if state and state.desired_running:
                self._process_manager.set_desired(entry, False)
                chk = self._table.item(row, COL_ENABLED)
                if chk:
                    chk.setCheckState(Qt.CheckState.Unchecked)
        self._table.blockSignals(False)
        self._profile_combo.blockSignals(True)
        self._profile_combo.setCurrentIndex(0)
        self._profile_combo.blockSignals(False)
        self._rebuild_table()  # Re-sort after deactivating all

    # ------------------------------------------------------------------
    # Profile management
    # ------------------------------------------------------------------

    def _reload_profiles(self) -> None:
        """Refresh the profile combo box from disk without triggering selection logic."""
        self._profile_combo.blockSignals(True)
        self._profile_combo.clear()
        self._profile_combo.addItem("— Profil auswählen —")
        for profile in self._profile_manager.load():
            self._profile_combo.addItem(profile.name)
        self._profile_combo.setCurrentIndex(0)
        self._profile_combo.blockSignals(False)

    def _on_profile_selected(self, index: int) -> None:
        """Apply the selected profile (uncheck all, then check profile entries)."""
        if index <= 0 or not self._config:
            return
        name = self._profile_combo.currentText()
        profiles = self._profile_manager.load()
        profile = next((p for p in profiles if p.name == name), None)
        if profile is None:
            return
        enabled_set = set(profile.enabled)
        
        # Get the actual ForwardEntry objects for this profile
        profile_entries = [e for e in self._config.forwards if e.name in enabled_set]
        
        # Check for port conflicts only between ACTIVE services in this profile
        conflict_warnings = []
        for entry in profile_entries:
            for other in profile_entries:
                if other.name != entry.name and other.local_port == entry.local_port:
                    # Check if these services are already active or will be enabled
                    entry_state = self._process_manager.get_state(entry.name)
                    other_state = self._process_manager.get_state(other.name)
                    entry_active = entry_state and entry_state.desired_running
                    other_active = other_state and other_state.desired_running
                    
                    # Only warn if at least one is already active
                    if entry_active or other_active:
                        # Avoid duplicate warnings
                        if f"{entry.name}" < f"{other.name}":
                            conflict_warnings.append(
                                f"  • {entry.name} (Port {entry.local_port}) ↔ {other.name} (Port {other.local_port})"
                            )
        
        if conflict_warnings:
            warning_msg = (
                f"Das Profil \"{name}\" hat Port-Konflikte mit aktiven Services:\n\n"
                + "\n".join(conflict_warnings) + "\n\n"
                "Trotzdem laden?"
            )
            reply = QMessageBox.warning(
                self,
                "Port-Konflikte im Profil",
                warning_msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        
        self._table.blockSignals(True)
        for row, entry in enumerate(self._display_entries):
            if self._table.isRowHidden(row):
                continue
            checked = entry.name in enabled_set
            chk = self._table.item(row, COL_ENABLED)
            if chk:
                chk.setCheckState(
                    Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
                )
            self._process_manager.set_desired(entry, checked)
        self._table.blockSignals(False)
        self._rebuild_table()  # Re-sort after applying profile

    def _on_save_profile(self) -> None:
        """Ask for a profile name and save the current checkbox selection."""
        # Pre-fill with current profile name if one is selected
        current_profile = self._profile_combo.currentText() if self._profile_combo.currentIndex() > 0 else ""
        name, ok = QInputDialog.getText(
            self, "Profil speichern", "Profilname:", text=current_profile
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        enabled_names = [
            entry.name
            for row, entry in enumerate(self._display_entries)
            if not self._table.isRowHidden(row)
            and self._process_manager.get_state(entry.name) is not None
            and self._process_manager.get_state(entry.name).desired_running
        ]
        self._profile_manager.save_profile(name, enabled_names)
        self._reload_profiles()
        # Select the just-saved profile in the combo
        idx = self._profile_combo.findText(name)
        if idx >= 0:
            self._profile_combo.blockSignals(True)
            self._profile_combo.setCurrentIndex(idx)
            self._profile_combo.blockSignals(False)

    def _on_delete_profile(self) -> None:
        """Delete the currently selected profile after confirmation."""
        index = self._profile_combo.currentIndex()
        if index <= 0:
            QMessageBox.information(self, "Profil löschen", "Kein Profil ausgewählt.")
            return
        name = self._profile_combo.currentText()
        reply = QMessageBox.question(
            self,
            "Profil löschen",
            f'Profil „{name}" wirklich löschen?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._profile_manager.delete_profile(name)
            self._reload_profiles()

    # ------------------------------------------------------------------
    # Window / tray behaviour
    # ------------------------------------------------------------------

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._restore_window()

    def _restore_window(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event: QCloseEvent) -> None:  # type: ignore[override]
        """Hide to system tray instead of closing."""
        event.ignore()
        self.hide()
        self._tray.showMessage(
            "Kubernetes Port Forward Manager",
            "Running in the background.\nDouble-click the tray icon to restore.",
            QSystemTrayIcon.MessageIcon.Information,
            2_500,
        )

    def _save_geometry(self) -> None:
        s = QSettings("portforward", "MainWindow")
        s.setValue("geometry", self.saveGeometry())

    def _restore_geometry(self) -> None:
        s = QSettings("portforward", "MainWindow")
        geometry = s.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        else:
            self.setMinimumSize(950, 420)
            self.resize(1100, 600)

    def _quit(self) -> None:
        self._save_geometry()
        self._refresh_timer.stop()
        if self._log_viewer_window and self._log_viewer_window.isVisible():
            self._log_viewer_window.close()
        self._process_manager.shutdown()
        if self._logger_manager:
            self._logger_manager.shutdown()
        self._tray.hide()
        QApplication.quit()
