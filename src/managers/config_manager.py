import os
from pathlib import Path
from typing import List

import yaml

from src.models.portforward_config import AppConfig, Profile, ProfileStore

_DEFAULT_CONFIG_CONTENT = """\
# Kubernetes Port Forward Manager - Configuration
#
# Each entry defines one kubectl port-forward command.
# Format: kubectl port-forward <resource> <local_port>:<remote_port> -n <namespace>
#
# Fields:
#   name        - Display name shown in the UI (must be unique)
#   resource    - Kubernetes resource, e.g. deployment/myapp, service/myservice
#   local_port  - Port on your local machine
#   remote_port - Port inside the container/service
#   namespace   - Kubernetes namespace (default: "default")
#   health_check_path - Optional HTTP path polled every 30 s, e.g. "/health"
#                       After 3 consecutive failures the forward is restarted.

forwards:
  - name: "Onboarding Service"
    resource: "deployment/onboarding"
    local_port: 9543
    remote_port: 8443
    namespace: default
    health_check_path: "/health"

# Logging configuration
# Logs are written asynchronously to avoid UI blocking
logging:
  enabled: true
  log_dir: "./logs"        # Directory where log files are stored (relative or absolute path)
  log_file: "portforward.log"  # Log filename (max 5 MB, keeps 5 backups)
"""


class ConfigManager:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path

    def load(self) -> AppConfig:
        if not self.config_path.exists():
            self._write_default()

        with open(self.config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data:
            return AppConfig()

        return AppConfig(**data)

    def save(self, config: AppConfig) -> None:
        """Save the AppConfig to the config file."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(config.model_dump(), f, allow_unicode=True, sort_keys=False)

    def _write_default(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(_DEFAULT_CONFIG_CONTENT, encoding="utf-8")

    def open_in_editor(self) -> None:
        """Open the config file with the system default editor."""
        os.startfile(str(self.config_path))

    @staticmethod
    def default_config_path() -> Path:
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home()
        return base / "portforward" / "config.yaml"


class ProfileManager:
    """Manages named profiles (sets of enabled forward names) stored in profiles.yaml."""

    def __init__(self, config_path: Path) -> None:
        self._profiles_path = config_path.parent / "profiles.yaml"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> List[Profile]:
        if not self._profiles_path.exists():
            return []
        with open(self._profiles_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not data:
            return []
        return ProfileStore(**data).profiles

    def save_profile(self, name: str, enabled_names: List[str]) -> None:
        """Create or overwrite a profile with *name*."""
        profiles = self.load()
        for p in profiles:
            if p.name == name:
                p.enabled = enabled_names
                break
        else:
            profiles.append(Profile(name=name, enabled=enabled_names))
        self._write(profiles)

    def delete_profile(self, name: str) -> None:
        profiles = [p for p in self.load() if p.name != name]
        self._write(profiles)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _write(self, profiles: List[Profile]) -> None:
        self._profiles_path.parent.mkdir(parents=True, exist_ok=True)
        store = ProfileStore(profiles=profiles)
        with open(self._profiles_path, "w", encoding="utf-8") as f:
            yaml.dump(store.model_dump(), f, allow_unicode=True, sort_keys=False)
