"""Server-side review access: original judgments are immutable, new sessions are account-bound."""

from ui.review_records import (ReviewError, RunLoadError, import_session, list_exports,
                               load_references, load_run, make_review)
from ui.reviewer_accounts import (bind_own_run, export_own, import_own, load_own, own_exports,
                                  require_identity, require_own_run, submitted_own)


def load_review(folder, locations, identity=None, *, own=False, allow_evaluation=False):
    """Never restore global latest baseline judgments into an account's own session."""
    if folder not in locations:
        raise RunLoadError("Choose a saved run folder from the list.")
    run = load_run(locations[folder], allow_evaluation=allow_evaluation)
    run["references"] = load_references(run["directory"], run["manifest"]["split"],
                                          allow_evaluation=allow_evaluation)
    if own:
        identity = require_identity(identity)
        run = bind_own_run(run, identity)
        reviews, restored = load_own(run, identity)
        run["restored_export"] = restored
        return run, reviews, ("Your previous review was restored." if restored else
                              "New account-specific review: every case starts Pending. Original judgments are hidden.")
    if identity is not None and not submitted_own(run, identity):
        raise ReviewError("Submit your own review for this run before opening original judgments for comparison.")
    names = list_exports(run)
    reviews = import_session(run, names[0]) if names else {}
    run.update(review_mode="baseline", review_owner=None, restored_export=names[0] if names else None)
    return run, reviews, "Original reviews — read-only. New reviews never replace this baseline."


def save_own(run, reviews, case, identity, decision, supported, notes, suggestion):
    identity = require_own_run(run, identity)
    if case is None:
        raise ReviewError("Choose a recorded case first.")
    review = make_review(case, identity.label, decision, supported, notes, suggestion)
    return {**reviews, case["case_id"]: review}


def export_for_account(run, reviews, identity):
    return export_own(run, reviews, identity)


def exports_for_view(run, identity):
    if run is None:
        return []
    if run.get("review_mode") == "mine":
        require_own_run(run, identity)
        return own_exports(run, identity)
    return list_exports(run)


def resume_for_view(run, name, identity):
    if run.get("review_mode") == "mine":
        require_own_run(run, identity)
        return import_own(run, name, identity)
    if identity is not None and not submitted_own(run, identity):
        raise ReviewError("Submit your own review before opening original judgments.")
    return import_session(run, name)
