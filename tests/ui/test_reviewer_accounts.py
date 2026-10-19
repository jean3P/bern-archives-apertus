"""Account separation uses synthetic fixtures and no Hugging Face/model calls."""

import json
import socket
from types import SimpleNamespace

import pytest

from test_run_review import make_run, inventory
from ui import review_access as access
from ui import reviewer_accounts as accounts
from ui.hf_review_auth import SessionIdentities, oauth_settings
from ui.review_records import ReviewError, export_session, load_run, make_review


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    run_dir = make_run(tmp_path / "runs" / "synthetic")
    baseline = tmp_path / "originals"
    account = tmp_path / "reviewer-exports"
    monkeypatch.setattr(accounts, "ACCOUNT_EXPORT_ROOT", account)
    monkeypatch.setattr(accounts, "EXPORT_ROOT", baseline)
    from ui.review_records import import_session, list_exports
    monkeypatch.setattr(access, "list_exports", lambda run: list_exports(run, baseline))
    monkeypatch.setattr(access, "import_session", lambda run, name: import_session(run, name, baseline))
    run = load_run(run_dir)
    original = {"SYN-01": make_review(run["cases"][0], "Jeni", "Correct", "1", "Original", "")}
    export_session(run, original, baseline)
    return run, {run_dir.name: str(run_dir)}, baseline, account, original


ALICE = accounts.ReviewerIdentity("synthetic-sub-alice", "alice_test")
BOB = accounts.ReviewerIdentity("synthetic-sub-bob", "bob_test")


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("No provider or model calls in these offline tests")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr("httpx.AsyncClient.send", denied)


def test_new_account_starts_pending_and_originals_are_immutable(workspace):
    run, locations, baseline, account, original = workspace
    before = inventory(baseline), inventory(run["directory"])
    mine, reviews, _ = access.load_review(run["directory"].name, locations, ALICE, own=True)
    assert reviews == {} and mine["review_owner"] == ALICE.key
    updated = access.save_own(mine, reviews, mine["cases"][0], ALICE, "Incorrect", "0", "Different", "Fixed")
    assert updated["SYN-01"]["reviewer"] == "Hugging Face @alice_test"
    session = access.export_for_account(mine, updated, ALICE)
    assert session.parent == account / ALICE.key
    assert accounts.import_own(mine, session.name, ALICE) == updated
    assert accounts.load_own(mine, BOB) == ({}, None)
    assert (inventory(baseline), inventory(run["directory"])) == before
    baseline_run, restored, _ = access.load_review(run["directory"].name, locations)
    assert restored == original and baseline_run["review_mode"] == "baseline"
    receipt = json.loads((session / accounts.IDENTITY_FILE).read_text())
    assert receipt["subject"] == ALICE.subject and receipt["baseline_reviews_copied"] is False
    assert receipt["independent_blind_review_certified"] is False


def test_anonymous_baseline_and_other_account_cannot_write(workspace):
    run, locations, *_ = workspace
    baseline, _, _ = access.load_review(run["directory"].name, locations)
    mine = accounts.bind_own_run(run, ALICE)
    for candidate, identity in [(baseline, ALICE), (mine, BOB), (mine, None)]:
        with pytest.raises(ReviewError):
            access.save_own(candidate, {}, run["cases"][0], identity, "Correct", "1", "", "")
        with pytest.raises(ReviewError):
            access.export_for_account(candidate, {}, identity)


def test_accounts_cannot_copy_labels_or_resume_another_export(workspace):
    run, _, _, _, original = workspace
    mine = accounts.bind_own_run(run, ALICE)
    with pytest.raises(ReviewError, match="another reviewer's"):
        accounts.export_own(mine, original, ALICE)
    session = accounts.export_own(mine, {}, ALICE)
    with pytest.raises(ReviewError, match="own exports"):
        accounts.import_own(accounts.bind_own_run(run, BOB), session.name, BOB)
    with pytest.raises(ReviewError):
        accounts.import_own(mine, "../../originals", ALICE)


def test_changed_receipt_or_content_is_rejected(workspace):
    run, *_ = workspace
    mine = accounts.bind_own_run(run, ALICE)
    session = accounts.export_own(mine, {}, ALICE)
    receipt_path = session / accounts.IDENTITY_FILE
    receipt = json.loads(receipt_path.read_text())
    receipt["subject"] = BOB.subject
    receipt_path.write_text(json.dumps(receipt))
    with pytest.raises(ReviewError, match="ownership"):
        accounts.import_own(mine, session.name, ALICE)
    receipt["subject"] = ALICE.subject
    receipt_path.write_text(json.dumps(receipt))
    with (session / "reviews.jsonl").open("a") as output:
        output.write("\n")
    with pytest.raises(ReviewError, match="ownership"):
        accounts.import_own(mine, session.name, ALICE)


def test_partial_export_does_not_unlock_original_judgments(workspace):
    run, locations, *_ = workspace
    mine = accounts.bind_own_run(run, ALICE)
    accounts.export_own(mine, {}, ALICE)
    with pytest.raises(ReviewError, match="Submit"):
        access.load_review(run["directory"].name, locations, ALICE)
    reviews = {}
    for case in run["cases"]:
        reviews = access.save_own(mine, reviews, case, ALICE, "Uncertain", "Not counted", "Review", "")
    accounts.export_own(mine, reviews, ALICE)
    assert accounts.submitted_own(mine, ALICE)
    baseline, restored, _ = access.load_review(run["directory"].name, locations, ALICE)
    assert baseline["review_mode"] == "baseline" and restored["SYN-01"]["reviewer"] == "Jeni"


def test_cannot_put_account_exports_under_originals(workspace):
    _, _, baseline, *_ = workspace
    for root in (baseline, baseline / "nested"):
        with pytest.raises(ReviewError, match="separate"):
            accounts.account_root(ALICE, root)


def test_rapid_exports_resume_latest_receipt_not_random_folder_suffix(workspace):
    run, *_ = workspace
    mine = accounts.bind_own_run(run, ALICE)
    first = accounts.export_own(mine, {}, ALICE)
    first.rename(first.parent / (run["directory"].name + "-99999999-old"))
    updated = access.save_own(mine, {}, run["cases"][0], ALICE, "Incorrect", "0", "Latest", "")
    second = accounts.export_own(mine, updated, ALICE)
    second = second.rename(second.parent / (run["directory"].name + "-00000000-new"))
    restored, name = accounts.load_own(mine, ALICE)
    assert name == second.name and restored == updated


def test_subject_is_stable_owner_and_invalid_profiles_fail():
    assert ALICE.key == accounts.ReviewerIdentity(ALICE.subject, "renamed").key
    for subject, username in [(None, "alice"), ("", "alice"), ("id", "../escape"), ("id", "<script>")]:
        with pytest.raises(ReviewError):
            accounts.ReviewerIdentity(subject, username)


def test_only_server_issued_session_identity_is_accepted(monkeypatch):
    store = SessionIdentities()
    key = store.issue(ALICE)
    assert store.gradio_identity(SimpleNamespace(username=key)) == ALICE
    assert store.gradio_identity(SimpleNamespace(username="alice_test")) is None
    assert store.gradio_identity(None) is None
    monkeypatch.setattr("ui.hf_review_auth.time.time", lambda: 10**12)
    assert store.get(key) is None


def test_callback_is_exact_and_loopback_http_only(monkeypatch):
    monkeypatch.setenv("BERN_REVIEW_HF_CLIENT_ID", "synthetic-client")
    monkeypatch.delenv("BERN_REVIEW_HF_REDIRECT_URI", raising=False)
    assert oauth_settings() == ("synthetic-client", "http://127.0.0.1:17863/auth/huggingface/callback")
    for uri in ("http://example.org/auth/huggingface/callback", "http://127.0.0.1/wrong",
                "http://127.0.0.1/auth/huggingface/callback?code=bad"):
        monkeypatch.setenv("BERN_REVIEW_HF_REDIRECT_URI", uri)
        with pytest.raises(ValueError):
            oauth_settings()


def test_ui_only_wires_account_guarded_save_and_export(workspace):
    from ui.run_review import build_app
    run, *_ = workspace
    app = build_app(str(run["directory"]), runs_root=run["directory"].parent, oauth_enabled=True)
    config = app.get_config_file()
    functions = {fn.api_name: fn.fn for fn in app.fns.values()}
    names = set(functions)
    assert "save_view" in names and "export_view" in names
    assert not names.intersection({"on_save_review", "on_export"})
    comps = {c.get("props", {}).get("label"): c for c in config["components"]}
    editor = comps["Your name (required only when saving an edit)"]
    save = next(d for d in config["dependencies"] if d.get("api_name") == "save_view")
    assert editor["id"] not in save["inputs"]
    baseline = {**run, "review_mode": "baseline", "review_owner": None}
    denied = functions["save_view"](baseline, {}, "All", "SYN-01", "Correct", "1", "", "", None)
    assert "Not saved" in denied[-1]
    assert "Not exported" in functions["export_view"](baseline, {}, None)
    restored = functions["show_form"](baseline, original := {
        "SYN-01": make_review(run["cases"][0], "Jeni", "Correct", "1", "Checked", "")}, "SYN-01", None)
    assert restored[1].get_config()["value"] == "1"
    assert restored[0].get_config()["interactive"] is False and restored[5] == "Jeni"
    from gradio.context import LocalContext
    token = LocalContext.in_event_listener.set(True)
    try:
        # In real queued callbacks new component objects are partial updates,
        # not readable fully initialized components.
        queued_form = functions["show_form"](baseline, original, "SYN-01", None)
        assert queued_form[1].constructor_args["value"] == "1"
    finally:
        LocalContext.in_event_listener.reset(token)
    # The guarded form must also render an editable, caller-bound account review.
    own_app = build_app(str(run["directory"]), runs_root=run["directory"].parent,
                        identity_provider=lambda request: ALICE, oauth_enabled=True)
    own_form = next(fn.fn for fn in own_app.fns.values() if fn.api_name == "show_form")
    editable = own_form(accounts.bind_own_run(run, ALICE), {}, "SYN-01", None)
    assert editable[0].get_config()["value"] == "Pending"
    assert editable[0].get_config()["interactive"] is True


def test_actual_oauth_server_guards_requests_without_provider_calls(workspace, monkeypatch):
    pytest.importorskip("authlib", reason="Install the optional review-auth group to test the OAuth server")
    pytest.importorskip("itsdangerous")
    from fastapi.testclient import TestClient
    from ui.hf_review_auth import build_authenticated_server
    run, *_ = workspace
    monkeypatch.setenv("BERN_REVIEW_HF_CLIENT_ID", "synthetic-client")
    monkeypatch.setenv("BERN_REVIEW_SESSION_SECRET", "synthetic-session-secret-" * 3)
    monkeypatch.delenv("BERN_REVIEW_HF_REDIRECT_URI", raising=False)
    monkeypatch.delenv("BERN_REVIEW_HF_CLIENT_SECRET", raising=False)
    app = build_authenticated_server(runs_root=run["directory"].parent)
    with TestClient(app) as first, TestClient(app) as other:
        assert first.get("/").status_code == 200
        first_cookie = first.cookies.get("bern_review_session")
        assert first_cookie
        assert other.get("/").status_code == 200
        # Unrecognised callback never creates a signed-in reviewer.
        assert first.get("/auth/huggingface/callback").status_code == 401
        # Bind even read requests to the signed browser, not only mutable form callbacks.
        assert first.get("/gradio_api/config?session_hash=synthetic-session").status_code != 403
        assert other.get("/gradio_api/config?session_hash=synthetic-session").status_code == 403
        assert first.post("/gradio_api/call/save_view", json={"data": []}).status_code == 404
        assert first.get("/auth/logout", follow_redirects=False).status_code == 303
