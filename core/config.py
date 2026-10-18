"""Small environment-based configuration; no credentials in source control."""

from dataclasses import dataclass, field
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
    api_key: str | None = field(default=None, repr=False)

    def __post_init__(self):
        parsed = urlparse(self.base_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("Use an HTTP(S) model-server URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path.rstrip("/") != "/v1":
            raise ValueError("Expected a /v1 URL without embedded credentials, query or fragment")
        if any(character.isspace() for character in parsed.netloc):
            raise ValueError("Invalid model-server address")
        if parsed.port is not None and parsed.port == 0:
            raise ValueError("Invalid model-server port")
        if self.timeout <= 0:
            raise ValueError("Timeout must be positive")


def settings() -> Settings:
    load_dotenv(ROOT / ".env", override=False)
    return Settings(
        base_url=os.getenv("BERN_APERTUS_BASE_URL", "http://127.0.0.1:8010/v1").rstrip("/"),
        model=os.getenv("BERN_APERTUS_MODEL", "swiss-ai/Apertus-v1.5-8B"),
        timeout=float(os.getenv("BERN_APERTUS_TIMEOUT", "120")),
        api_key=os.getenv("BERN_APERTUS_API_KEY") or None,
    )
