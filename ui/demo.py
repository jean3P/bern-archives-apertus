"""Load labelled DEMO fixtures for the interface. These are not model results."""

import json
from pathlib import Path

from contracts import validate_response

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "ui"


def load_demo_response(name: str = "answered") -> dict:
    """Read fixtures/ui/<name>.demo.json and check its shape."""
    path = FIXTURES / f"{name}.demo.json"
    response = json.loads(path.read_text(encoding="utf-8"))
    validate_response(response)
    return response