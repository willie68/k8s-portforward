from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIntValidator
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from src.models.portforward_config import ForwardEntry


class ForwardDialog(QDialog):
    """Dialog for creating or editing a ForwardEntry."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        entry: Optional[ForwardEntry] = None,
        existing_names: Optional[list[str]] = None,
    ) -> None:
        super().__init__(parent)
        self._existing_names = existing_names or []
        self._edit_mode = entry is not None
        self._original_name = entry.name if entry else ""

        self.setWindowTitle("Port Forward bearbeiten" if self._edit_mode else "Neuer Port Forward")
        self.setMinimumWidth(420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui()

        if entry:
            self._populate(entry)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        layout.addLayout(form)

        self._name = QLineEdit()
        self._name.setPlaceholderText("z.B. My Service")
        form.addRow("Name *", self._name)

        self._resource = QLineEdit()
        self._resource.setPlaceholderText("z.B. deployment/myapp oder service/myservice")
        form.addRow("Resource *", self._resource)

        self._local_port = QLineEdit()
        self._local_port.setValidator(QIntValidator(1, 65535, self))
        self._local_port.setPlaceholderText("1–65535")
        form.addRow("Lokaler Port *", self._local_port)

        self._remote_port = QLineEdit()
        self._remote_port.setValidator(QIntValidator(1, 65535, self))
        self._remote_port.setPlaceholderText("1–65535")
        form.addRow("Remote Port *", self._remote_port)

        self._context = QLineEdit()
        self._context.setPlaceholderText("optional – kubectl context")
        form.addRow("Context", self._context)

        # Health check section
        form.addRow(QLabel(""))
        form.addRow(QLabel("<b>Health Check</b> (optional)"))

        self._health_path = QLineEdit()
        self._health_path.setPlaceholderText("z.B. /health oder /actuator/health")
        form.addRow("Pfad", self._health_path)

        self._health_tls = QCheckBox("HTTPS verwenden")
        form.addRow("TLS", self._health_tls)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate(self, entry: ForwardEntry) -> None:
        self._name.setText(entry.name)
        self._resource.setText(entry.resource)
        self._local_port.setText(str(entry.local_port))
        self._remote_port.setText(str(entry.remote_port))
        self._context.setText(entry.context or "")
        self._health_path.setText(entry.health_check_path or "")
        self._health_tls.setChecked(entry.health_check_tls)

    # ------------------------------------------------------------------
    # Validation & result
    # ------------------------------------------------------------------

    def _on_accept(self) -> None:
        errors = []

        name = self._name.text().strip()
        resource = self._resource.text().strip()
        local_port_str = self._local_port.text().strip()
        remote_port_str = self._remote_port.text().strip()

        if not name:
            errors.append("Name darf nicht leer sein.")
        elif name != self._original_name and name in self._existing_names:
            errors.append(f'Ein Eintrag mit dem Namen "{name}" existiert bereits.')

        if not resource:
            errors.append("Resource darf nicht leer sein.")

        if not local_port_str:
            errors.append("Lokaler Port darf nicht leer sein.")
        elif not (1 <= int(local_port_str) <= 65535):
            errors.append("Lokaler Port muss zwischen 1 und 65535 liegen.")

        if not remote_port_str:
            errors.append("Remote Port darf nicht leer sein.")
        elif not (1 <= int(remote_port_str) <= 65535):
            errors.append("Remote Port muss zwischen 1 und 65535 liegen.")

        health_path = self._health_path.text().strip()
        if health_path and not health_path.startswith("/"):
            errors.append("Health-Check-Pfad muss mit '/' beginnen.")

        if errors:
            QMessageBox.warning(
                self,
                "Eingabefehler",
                "\n".join(f"• {e}" for e in errors),
            )
            return

        self.accept()

    def result_entry(self) -> ForwardEntry:
        """Return the ForwardEntry built from the dialog inputs. Call after exec() == Accepted."""
        context_val = self._context.text().strip() or None
        health_path = self._health_path.text().strip() or None
        return ForwardEntry(
            name=self._name.text().strip(),
            resource=self._resource.text().strip(),
            local_port=int(self._local_port.text().strip()),
            remote_port=int(self._remote_port.text().strip()),
            context=context_val,
            health_check_path=health_path,
            health_check_tls=self._health_tls.isChecked(),
        )
