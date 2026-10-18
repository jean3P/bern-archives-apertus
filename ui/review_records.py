"""Read-only loading of saved J4 development runs for human review (S5)."""

import re
from pathlib import Path

from core.evaluation_records import child_file, read_json, read_jsonl, verify_directory

from core.evaluation_records import read_json, read_jsonl, verify_directory


class RunLoadError(ValueError):
    """A saved run could not be opened safely; the message is shown to the user."""

CASE_FILES = {
    "input.json", "response.json", "retrieved_sources.json", "evidence.json",
    "validated_claims.json", "summary.json", "events.jsonl",
}
SAFE_CASE_ID = re.compile(r"[A-Za-z0-9_-]+")

def load_run(run_dir) -> dict:
    """Check the seal, then read the manifest and the ordered case records."""
    directory = Path(run_dir).resolve()
    if not (directory / "_COMPLETE.json").is_file():
        raise RunLoadError("Not a completed saved run (no _COMPLETE.json).")
    try:
        seal = verify_directory(directory)
    except ValueError as exc:
        raise RunLoadError(f"Run changed or incomplete: {exc}") from exc
    manifest = read_json(directory / "run-manifest.json")
    if manifest.get("split") != "development":
        raise RunLoadError("Only development runs can be reviewed in this version.")
    cases = read_jsonl(directory / "case-scores.jsonl")
    return {"directory": directory, "seal": seal, "manifest": manifest, "cases": cases}


def load_references(directory) -> dict:
    """Draft development references by case ID. Never opens the evaluation set."""
    path = child_file(directory, "references/development-questions.jsonl")
    return {ref["case_id"]: ref for ref in read_jsonl(path)}


def load_case_file(directory, case_id: str, name: str):
    """One known artifact of one case, or None when it was not recorded."""
    if not SAFE_CASE_ID.fullmatch(case_id) or name not in CASE_FILES:
        raise RunLoadError("Unsafe or unknown case file request.")
    try:
        path = child_file(directory, f"cases/{case_id}/{name}")
    except ValueError:
        return None
    return read_jsonl(path) if name.endswith(".jsonl") else read_json(path)