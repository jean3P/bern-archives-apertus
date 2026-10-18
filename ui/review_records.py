"""Read-only loading of saved J4 development runs for human review (S5)."""

import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from core.evaluation_records import (child_file, create_output, digest, read_json, read_jsonl,
                                     verify_directory, write_json, write_jsonl)
from core.evaluation_scoring import load_reviews


class RunLoadError(ValueError):
    """A saved run could not be opened safely; the message is shown to the user."""


CASE_FILES = {
    "input.json", "response.json", "retrieved_sources.json", "evidence.json",
    "validated_claims.json", "summary.json", "events.jsonl",
}
SAFE_CASE_ID = re.compile(r"[A-Za-z0-9_-]+")
EXPORT_ROOT = Path(__file__).resolve().parent.parent / "runs" / "review-exports"
REVIEW_FILE = "reviews.jsonl"
CORRECTIONS_FILE = "suggested-corrections.json"


DECISIONS = {"Pending": None, "Correct": "correct", "Incorrect": "incorrect", "Uncertain": "uncertain"}
NOT_COUNTED = "Not counted"


class ReviewError(ValueError):
    """A review the scorer would reject; the message is shown to the reviewer."""

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


def make_review(case: dict, reviewer, decision_label, supported_label, notes, suggestion) -> dict:
    """Check one human review against the scorer's rules before keeping it in memory."""
    if decision_label not in DECISIONS:
        raise ReviewError("Choose Pending, Correct, Incorrect or Uncertain.")
    decision = DECISIONS[decision_label]
    reviewer = (reviewer or "").strip()
    suggestion = (suggestion or "").strip()
    supported = None if supported_label in (None, NOT_COUNTED) else int(supported_label)
    claims = case["claim_count"]

    if (decision is not None or suggestion) and not reviewer:
        raise ReviewError("Enter your name: a decision or suggestion needs a named human reviewer.")
    if decision is None and supported is not None:
        raise ReviewError("A Pending review cannot have a supported-claim count. Choose a decision first.")
    if supported is not None and not 0 <= supported <= claims:
        raise ReviewError(f"Supported claims must be between 0 and {claims}.")
    if decision == "correct" and case["definitive_failure"]:
        raise ReviewError("This response failed technically, so it cannot be marked Correct.")
    if decision == "correct" and case["observed_status"] == "answered" and supported != claims:
        raise ReviewError(f"Correct needs all {claims} claim(s) checked as supported.")

    return {"reviewer": reviewer or None, "decision": decision, "supported_claims": supported,
            "notes": notes or "", "suggestion": suggestion}


def scorer_reviews(run: dict, reviews: dict) -> list:
    """One record per case in run order, with exactly the scorer's six fields; Pending is null."""
    records = []
    for case in run["cases"]:
        review = reviews.get(case["case_id"], {})
        records.append({
            "case_id": case["case_id"],
            "review_binding": case["review_binding"],
            "reviewer": review.get("reviewer"),
            "decision": review.get("decision"),
            "supported_claims": review.get("supported_claims"),
            "notes": review.get("notes", ""),
        })
    return records


def suggested_corrections(run: dict, reviews: dict, seal_sha256: str) -> dict:
    """Human suggestions kept apart from scoring and from the model output."""
    by_id = {case["case_id"]: case for case in run["cases"]}
    return {
        "label": "Human suggestion, not generated output",
        "run": run["directory"].name,
        "run_seal_sha256": seal_sha256,
        "corrections": [
            {"case_id": case_id, "review_binding": by_id[case_id]["review_binding"],
             "reviewer": review["reviewer"], "suggested_answer": review["suggestion"],
             "notes": review.get("notes", "")}
            for case_id, review in reviews.items() if review.get("suggestion")
        ],
    }


def export_session(run: dict, reviews: dict, export_root=EXPORT_ROOT) -> Path:
    """Write the reviews and suggestions to a new folder outside the run; never overwrite anything."""
    try:
        verify_directory(run["directory"])
    except ValueError as exc:
        raise RunLoadError(f"Run changed or incomplete, so the review cannot be exported: {exc}") from exc
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    session = Path(export_root) / f'{run["directory"].name}-{stamp}-{uuid4().hex[:8]}'
    try:
        create_output(session, protected=[run["directory"]])
    except (OSError, ValueError) as exc:
        raise RunLoadError(f"Cannot create the export folder: {exc}") from exc
    write_jsonl(session / REVIEW_FILE, scorer_reviews(run, reviews))
    load_reviews(session / REVIEW_FILE, run["cases"])
    seal_sha256 = digest(run["directory"] / "_COMPLETE.json")
    write_json(session / CORRECTIONS_FILE, suggested_corrections(run, reviews, seal_sha256))
    return session
