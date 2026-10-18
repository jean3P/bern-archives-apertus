"""Small environment-based configuration; no credentials in source control."""

from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    base_url: str = "http://127.0.0.1:8010/v1"
    model: str = "swiss-ai/Apertus-v1.5-8B"
    timeout: float = 120.0

    def __post_init__(self):
        parsed = urlparse(self.base_url)
        if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("Use the private loopback endpoint or an SSH tunnel")
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path.rstrip("/") != "/v1":
            raise ValueError("Expected a plain loopback /v1 URL")
        if parsed.port == 8000:
            raise ValueError("Port 8000 is reserved for Track 2A")
        if self.timeout <= 0:
            raise ValueError("Timeout must be positive")


def settings() -> Settings:
    load_dotenv(ROOT / ".env", override=False)
    return Settings(
        base_url=os.getenv("BERN_APERTUS_BASE_URL", "http://127.0.0.1:8010/v1").rstrip("/"),
        model=os.getenv("BERN_APERTUS_MODEL", "swiss-ai/Apertus-v1.5-8B"),
        timeout=float(os.getenv("BERN_APERTUS_TIMEOUT", "120")),
    )
