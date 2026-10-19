"""Separate authenticated review exports from the immutable original review baseline."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from core.evaluation_records import digest
from ui.review_records import (CORRECTIONS_FILE, EXPORT_ROOT, REVIEW_FILE, ReviewError,
                               export_session, import_session, list_exports)


ACCOUNT_EXPORT_ROOT = EXPORT_ROOT.parent / "reviewer-exports"
IDENTITY_FILE = "reviewer-identity.json"


@dataclass(frozen=True)
class ReviewerIdentity:
    """Constructed only from the server-validated Hugging Face session, not a form field."""
    subject: str
    username: str

    def __post_init__(self):
        if (not isinstance(self.subject, str) or not 1 <= len(self.subject) <= 256
                or not isinstance(self.username, str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", self.username)):
            raise ReviewError("Invalid authenticated reviewer identity.")

    @property
    def key(self):
        return hashlib.sha256(("https://huggingface.co\0" + self.subject).encode()).hexdigest()

    @property
    def label(self):
        return f"Hugging Face @{self.username}"


def require_identity(identity):
    if not isinstance(identity, ReviewerIdentity):
        raise ReviewError("Sign in with Hugging Face before starting or saving your own review.")
    return identity


def account_root(identity, root=None):
    identity = require_identity(identity)
    root = Path(ACCOUNT_EXPORT_ROOT if root is None else root).resolve()
    baseline = EXPORT_ROOT.resolve()
    if root == baseline or baseline in root.parents:
        raise ReviewError("Authenticated exports must be separate from original reviews.")
    path = root / identity.key
    if path.is_symlink():
        raise ReviewError("Invalid reviewer storage location.")
    return path


def bind_own_run(run, identity):
    identity = require_identity(identity)
    return {**run, "review_mode": "mine", "review_owner": identity.key,
            "review_account_label": identity.label}


def require_own_run(run, identity):
    identity = require_identity(identity)
    if not run or run.get("review_mode") != "mine" or run.get("review_owner") != identity.key:
        raise ReviewError("Original reviews are read-only. Start or resume your own review first.")
    return identity


def own_exports(run, identity, root=None):
    require_identity(identity)
    directory = account_root(identity, root)
    names = list_exports(run, directory)

    def created(name):
        try:
            receipt = json.loads((directory / name / IDENTITY_FILE).read_text(encoding="utf-8"))
            stamp = datetime.fromisoformat(receipt["created_at_utc"])
            if stamp.tzinfo is None:
                raise ValueError("Missing timezone")
            return stamp, name
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ReviewError("An account export has an invalid identity receipt; operator review is required.") from exc

    # Baseline folder names have only second precision and random suffixes.
    # Use this account's full-precision receipt, not lexical suffix order.
    return sorted(names, key=created, reverse=True)


def import_own(run, session_name, identity, root=None):
    identity = require_identity(identity)
    directory = account_root(identity, root)
    if session_name not in list_exports(run, directory):
        raise ReviewError("Choose one of your own exports for this run.")
    session = directory / session_name
    identity_path = session / IDENTITY_FILE
    if identity_path.is_symlink():
        raise ReviewError("Invalid review identity receipt.")
    try:
        receipt = json.loads(identity_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReviewError("This export has no valid authenticated ownership receipt.") from exc
    if (receipt.get("issuer") != "https://huggingface.co" or receipt.get("subject") != identity.subject
            or receipt.get("run_seal_sha256") != digest(run["directory"] / "_COMPLETE.json")
            or receipt.get("files") != {name: digest(session / name) for name in (REVIEW_FILE, CORRECTIONS_FILE)}):
        raise ReviewError("Export ownership, run or content does not match.")
    reviews = import_session(run, session_name, directory)
    # Fail closed on renamed accounts instead of silently relabelling historical authors.
    if any(row.get("reviewer") not in (None, identity.label) for row in reviews.values()):
        raise ReviewError("The stored account label differs; operator review is required before editing.")
    return reviews


def load_own(run, identity, root=None):
    names = own_exports(run, identity, root)
    return (import_own(run, names[0], identity, root) if names else {}), (names[0] if names else None)


def export_own(run, reviews, identity, root=None):
    identity = require_own_run(run, identity)
    if any(row.get("reviewer") not in (None, identity.label) for row in reviews.values()):
        raise ReviewError("Your export must not contain another reviewer's judgments.")
    session = export_session(run, reviews, account_root(identity, root))
    receipt = {"version": 1, "issuer": "https://huggingface.co", "subject": identity.subject,
               "username": identity.username, "reviewer_label": identity.label,
               "created_at_utc": datetime.now(timezone.utc).isoformat(),
               "run_seal_sha256": digest(run["directory"] / "_COMPLETE.json"),
               "files": {name: digest(session / name) for name in (REVIEW_FILE, CORRECTIONS_FILE)},
               "baseline_reviews_copied": False, "independent_blind_review_certified": False}
    with (session / IDENTITY_FILE).open("x", encoding="utf-8") as output:
        json.dump(receipt, output, ensure_ascii=False, indent=2)
        output.write("\n")
    return session


def submitted_own(run, identity, root=None):
    reviews, _ = load_own(run, identity, root)
    return bool(run["cases"]) and all(reviews.get(c["case_id"], {}).get("decision") in
                                      ("correct", "incorrect", "uncertain") for c in run["cases"])
