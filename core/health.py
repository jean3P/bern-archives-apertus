"""uv run python -m core.health [--generate] [--out runs/j1-smoke.json]."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from core.apertus import ApertusClient
from core.config import settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.out and args.out.exists():
        raise SystemExit("Choose a new output path; preserve the previous smoke receipt")
    client = ApertusClient(settings())
    try:
        result = client.smoke() if args.generate else {"connection_ok": True, "models_response": client.models(), "generation_posts": 0}
    finally:
        client.close()
    result["checked_at_utc"] = datetime.now(timezone.utc).isoformat()
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
