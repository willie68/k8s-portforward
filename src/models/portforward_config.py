from typing import List, Optional

from pydantic import BaseModel, field_validator


class ForwardEntry(BaseModel):
    """A single kubectl port-forward definition."""

    name: str
    resource: str  # e.g. "deployment/onboarding" or "service/myservice"
    local_port: int
    remote_port: int
    context: Optional[str] = None  # reserved for future multi-cluster support
    health_check_path: Optional[str] = None  # e.g. "/health" – checked every 30 s when running
    health_check_tls: bool = False            # True → https, False → http

    @field_validator("local_port", "remote_port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError(f"Port {v} is out of valid range (1-65535)")
        return v

    @property
    def port_mapping(self) -> str:
        return f"{self.local_port}:{self.remote_port}"


class LoggingConfig(BaseModel):
    """Logging configuration."""

    enabled: bool = True
    log_dir: str = "./logs"  # Path where log files are created
    log_file: str = "portforward.log"  # Log filename


class AppConfig(BaseModel):
    """Root configuration loaded from config.yaml."""

    forwards: List[ForwardEntry] = []
    logging: LoggingConfig = LoggingConfig()


class Profile(BaseModel):
    """A named set of forward names that should be enabled together."""

    name: str
    enabled: List[str] = []  # list of ForwardEntry.name values


class ProfileStore(BaseModel):
    """Root of profiles.yaml."""

    profiles: List[Profile] = []
