"""Saved-run review screen: no models, search or changes to original results."""

import html
import json
from pathlib import Path

import gradio as gr

from ui.review_records import (DECISIONS, NOT_COUNTED, ReviewError, RunLoadError, export_session,
                               discover_runs, import_session, list_exports, load_case_file, load_references, load_run,
                               make_review)


BANNER = "## SAVED RUN REVIEW — recorded results, not a fresh LIVE answer"

# Project-team affiliations supplied by Jean; historical review authors stay exact.
REVIEWER_INSTITUTIONS = {
    "jeni": "BFH — Berner Fachhochschule",
    "jean": "University of Neuchâtel",
    "jean (user-authorized assistant amendment)": "University of Neuchâtel",
}

THEME = gr.themes.Default().set(
    block_title_text_size="*text_lg",
    block_title_text_weight="600",
    input_text_size="18px",
)

CSS = """
.review-panel, .review-panel div, .review-panel li { font-size: 17px !important; line-height: 1.6; }
.review-panel strong { font-weight: 600; }
.source-original { font-size: 18px; white-space: pre-wrap; }
.draft-label { font-weight: 700; color: #6d4c00; background: #fff8e1; padding: 2px 8px; display: inline-block; }
.load-error { font-weight: 700; color: #8e1c1c; }
.review-ok { font-weight: 600; color: #1b5e20; }
.timeline { border-collapse: collapse; width: 100%; }
.timeline th, .timeline td { border-bottom: 1px solid #ddd; padding: 4px 8px; text-align: left; vertical-align: top; }
"""


def esc(value) -> str:
    """Escape any value for HTML; None is shown as Unavailable, never invented."""
    return "<em>Unavailable</em>" if value is None else html.escape(str(value))


def rows(pairs) -> str:
    """Bold label plus escaped value, one line each."""
    return "".join(f"<div><strong>{name}:</strong> {esc(value)}</div>" for name, value in pairs)


def run_summary(run: dict) -> str:
    manifest = run["manifest"]
    return '<div class="review-panel">' + rows([
        ("Run", run["directory"].name),
        ("Split", manifest.get("split")),
        ("Review scope", "Previously used evaluation questions; not an untouched test set"
         if manifest.get("split") == "evaluation" else "Development questions"),
        ("Reference status", manifest.get("reference_review", {}).get("status")),
        ("Recorded at (UTC)", manifest.get("created_at_utc")),
        ("Model", manifest.get("settings", {}).get("model")),
        ("Code version", manifest.get("candidate", {}).get("git_commit")),
        ("Cases", len(run["cases"])),
    ]) + "</div>"


def question_answer_html(case: dict) -> str:
    response = case.get("response") or {}
    scope = case["input"].get("transcription_id")
    return '<div class="review-panel">' + rows([
        ("Case", case["case_id"]),
        ("Question", case["input"]["question"]),
        ("Transcription", "None (no filter)" if scope is None else scope),
        ("Backend status", case.get("observed_status")),
        ("Generated answer", response.get("answer") or "No answer was produced"),
        ("Message", response.get("message") or "None"),
    ]) + "</div>"


def evidence_html(evidence) -> str:
    if evidence is None:
        return '<div class="review-panel"><em>Evidence file unavailable for this case.</em></div>'
    if not evidence["packet"]:
        return '<div class="review-panel"><em>No passages were delivered to the model.</em></div>'
    cards = []
    for item in evidence["packet"]:
        records = "".join(rows([
            ("Record", record["record_id"]),
            ("Survey question", f'{record.get("question_number") or "unknown"} — {record.get("survey_question") or ""}'),
            ("Archive reference", record.get("archive_reference") or "unknown"),
            ("Page", "Page not verified" if record.get("pdf_page_index") is None else record["pdf_page_index"]),
        ]) for record in item["records"])
        cards.append(f'<p class="source-original">{esc(item["passage"])}</p>{records}')
    return '<div class="review-panel">' + "<hr>".join(cards) + "</div>"


def reference_html(reference) -> str:
    if reference is None:
        return '<div class="review-panel"><em>No draft reference for this case.</em></div>'
    facts = "".join(f"<li>{esc(fact)}</li>" for fact in reference.get("required_facts", []))
    quotes = "".join(
        f'<li>Answer {esc(item["answer_id"])}: <span class="source-original">{esc(item["quote"])}</span></li>'
        for item in reference.get("evidence", []))
    return ('<div class="review-panel"><p class="draft-label">DRAFT REFERENCE — not approved truth</p>'
            + rows([("Expected status", reference.get("expected_status"))])
            + f"<div><strong>Required facts:</strong><ul>{facts or '<li>None</li>'}</ul></div>"
            + f"<div><strong>Known source quotations:</strong><ul>{quotes or '<li>None</li>'}</ul></div></div>")


TABLE_HEADERS = ["Case", "Question", "Backend status", "Review", "Duration (s)"]


def decision_label(review) -> str:
    """Screen word for a stored decision; no review yet means Pending."""
    stored = (review or {}).get("decision")
    return next(label for label, value in DECISIONS.items() if value == stored)


FILTERS = ["All", "Pending", "Correct", "Incorrect", "Uncertain", "Technical error"]


def is_technical_error(case) -> bool:
    """Transport/receipt failures, not every mismatch against a draft reference."""
    return (case.get("observed_status") in ("error", "receipt_error")
            or not case.get("attempted", True) or case.get("protocol_valid") is False
            or case.get("response_contract_valid") is False)


def matches_filter(case, reviews, choice) -> bool:
    if choice == "All":
        return True
    if choice == "Technical error":
        return is_technical_error(case)
    return decision_label(reviews.get(case["case_id"])) == choice


def visible_case_ids(run, reviews, choice) -> list:
    """Case IDs that pass the filter, in run order."""
    if run is None:
        return []
    return [case["case_id"] for case in run["cases"] if matches_filter(case, reviews or {}, choice)]


def review_progress(run, reviews, choice) -> str:
    """How many cases are shown, plus review counts with their denominator (not final accuracy)."""
    total = len(run["cases"])
    shown = len(visible_case_ids(run, reviews, choice))
    counts = " · ".join(f"{name}: {len(visible_case_ids(run, reviews, name))}" for name in FILTERS[1:])
    return (f'<div class="review-panel"><strong>Showing {esc(choice)}:</strong> {shown} of {total} cases<br>'
            f"<strong>Review progress (not final accuracy):</strong> {esc(counts)}</div>")


def case_table(run, reviews=None, choice="All") -> list:
    """One row per recorded case that passes the filter, in run order."""
    reviews = reviews or {}
    table = []
    for case in run["cases"]:
        if not matches_filter(case, reviews, choice):
            continue
        seconds = case.get("total_seconds")
        table.append([
            case["case_id"],
            case["input"]["question"],
            case.get("observed_status") or "not attempted",
            decision_label(reviews.get(case["case_id"])),
            "Not measured" if seconds is None else round(seconds, 2),
        ])
    return table


def step_case(run, reviews, choice, case_id, offset):
    """Previous/next case among the filtered ones, staying within the first and last."""
    case_ids = visible_case_ids(run, reviews, choice)
    if not case_ids:
        return case_id
    if case_id not in case_ids:
        return case_ids[0]
    position = case_ids.index(case_id)
    return case_ids[max(0, min(len(case_ids) - 1, position + offset))]


def on_previous(run, reviews, choice, case_id):
    return step_case(run, reviews, choice, case_id, -1)


def on_next(run, reviews, choice, case_id):
    return step_case(run, reviews, choice, case_id, +1)


def on_filter(run, reviews, choice):
    """Refresh the table and counts for the chosen filter."""
    if run is None:
        return [], ""
    return case_table(run, reviews, choice), review_progress(run, reviews, choice)


def on_table_select(dirty, evt: gr.SelectData):
    """Clicking any cell of a row selects that row's case, unless the form has unsaved edits."""
    if dirty:
        return gr.skip()
    return evt.row_value[0]


def on_load(run_path, allow_evaluation=False, *, export_root=None):
    """Load a run and its newest checked export; never hide a failed resume as Pending."""
    try:
        run = load_run(run_path, allow_evaluation=allow_evaluation)
        run["references"] = load_references(run["directory"], run["manifest"]["split"],
                                             allow_evaluation=allow_evaluation)
        names = list_exports(run) if export_root is None else list_exports(run, export_root)
        run["restored_export"] = names[0] if names else None
        reviews = ((import_session(run, names[0]) if export_root is None
                    else import_session(run, names[0], export_root)) if names else {})
    except (RunLoadError, ReviewError, ValueError, OSError) as exc:
        message = (f'<p class="load-error">Could not load run or restore its latest saved review: {esc(exc)}. '
                   'Saved files were not changed; no older export was silently substituted.</p>')
        return None, message, [], gr.Dropdown(choices=[], value=None), {}
    case_ids = [case["case_id"] for case in run["cases"]]
    first = case_ids[0] if case_ids else None
    if names:
        reviewed = sum(review.get("decision") is not None for review in reviews.values())
        message = (f'<p class="review-ok">Restored saved reviews: {reviewed} of {len(case_ids)} cases '
                   f'from {esc(names[0])}. Decisions, notes and suggestions are loaded; '
                   'the original model answers and saved export are unchanged.</p>')
    else:
        message = ('<p class="review-panel">No saved review export was found for this run. '
                   'Starting a new review with all cases Pending.</p>')
    return (run, run_summary(run) + message, case_table(run, reviews),
            gr.Dropdown(choices=case_ids, value=first), reviews)


def on_load_folder(folder_name, locations, allow_evaluation=False):
    """Resolve a displayed folder name through the server's known-run mapping only."""
    if not isinstance(folder_name, str) or folder_name not in locations:
        return (None, '<p class="load-error">Choose a saved run folder from the list.</p>',
                [], gr.Dropdown(choices=[], value=None), {})
    return on_load(locations[folder_name], allow_evaluation)


def on_select(run, case_id):
    """Show one case; clear all panels when nothing valid is selected."""
    if run is None or case_id is None:
        return "", "", ""
    case = next((c for c in run["cases"] if c["case_id"] == case_id), None)
    if case is None:
        return '<p class="load-error">Unknown case.</p>', "", ""
    try:
        evidence = load_case_file(run["directory"], case_id, "evidence.json")
    except (RunLoadError, ValueError, OSError) as exc:
        return f'<p class="load-error">Could not read this case: {esc(exc)}</p>', "", ""
    return question_answer_html(case), evidence_html(evidence), reference_html(run["references"].get(case_id))


TECHNICAL_FILES = {
    "Input (input.json)": "input.json",
    "Final output (response.json)": "response.json",
    "Retrieved sources (retrieved_sources.json)": "retrieved_sources.json",
    "Evidence delivered to the model (evidence.json)": "evidence.json",
    "Validated claims (validated_claims.json)": "validated_claims.json",
    "Calls, retries and timing (summary.json)": "summary.json",
    "Model requests and responses (events.jsonl)": "events.jsonl",
    "Question-to-field bindings (binding_plan.json)": "binding_plan.json",
    "Field-owned evidence (binding_evidence.json)": "binding_evidence.json",
    "Recorded answer parts (binding_answer.json)": "binding_answer.json",
    "Unresolved-evidence hold (binding_hold.json)": "binding_hold.json",
    "Source-derived completeness checks (binding_completeness.json)": "binding_completeness.json",
}


def readable_event(event: dict) -> dict:
    """A display copy of one event; a JSON response body is shown parsed, the record is unchanged."""
    shown = dict(event)
    if isinstance(shown.get("body"), str):
        try:
            shown["body"] = json.loads(shown["body"])
        except ValueError:
            pass
    return shown


def pretty_json(name: str, value) -> str:
    """Read-only text for the JSON viewer; never invents content for a missing file."""
    if value is None:
        return f"Unavailable: {name} was not recorded for this case."
    if name.endswith(".jsonl"):
        value = [readable_event(event) for event in value]
    return json.dumps(value, ensure_ascii=False, indent=2)


def timeline_html(case: dict, events) -> str:
    """Recorded stages in order, plus the case's call/retry/timing counts."""
    tokens = case.get("token_usage") or {}
    seconds = case.get("total_seconds")
    header = rows([
        ("Generation calls", case.get("generation_posts_attempted")),
        ("Format retries", case.get("format_retries")),
        ("Total time (s)", "Not measured" if seconds is None else round(seconds, 2)),
        ("Prompt / generated tokens",
         f'{tokens.get("prompt_tokens", "Not measured")} / {tokens.get("completion_tokens", "Not measured")}'),
    ])
    if events is None:
        return f'<div class="review-panel">{header}<p><em>Event log unavailable for this case.</em></p></div>'
    lines = []
    for number, event in enumerate(events, start=1):
        if event.get("event") == "retrieval":
            detail = (f'code {event.get("question_code") or "none"}, query "{event.get("query") or ""}", '
                      f'{len(event.get("returned_record_ids") or [])} record(s) returned')
        else:
            detail = ""
        took = event.get("seconds")
        lines.append("<tr>" + "".join(f"<td>{esc(cell)}</td>" for cell in [
            number, event.get("at_utc"), event.get("event"), event.get("stage") or "",
            event.get("http_status") or "", "" if took is None else round(took, 3), detail]) + "</tr>")
    head = "".join(f"<th>{name}</th>" for name in ["#", "Time (UTC)", "Event", "Stage", "HTTP", "Seconds", "Details"])
    return (f'<div class="review-panel">{header}<table class="timeline"><tr>{head}</tr>'
            + "".join(lines) + "</table></div>")


def on_show_technical(run, case_id, artifact_label):
    """Timeline plus one raw artifact for the selected case; cleared when nothing valid is selected."""
    case = find_case(run, case_id)
    if case is None:
        return "", ""
    name = TECHNICAL_FILES.get(artifact_label, "input.json")
    try:
        events = load_case_file(run["directory"], case_id, "events.jsonl")
        artifact = events if name == "events.jsonl" else load_case_file(run["directory"], case_id, name)
    except (RunLoadError, ValueError, OSError) as exc:
        return f'<p class="load-error">Could not read technical details: {esc(exc)}</p>', ""
    return timeline_html(case, events), pretty_json(name, artifact)


def find_case(run, case_id):
    """The recorded case with this ID, or None."""
    if run is None:
        return None
    return next((c for c in run["cases"] if c["case_id"] == case_id), None)


def on_show_reviewer(run, reviews, case_id):
    """Display the decision's stored author, never use it as the current editor's identity."""
    if find_case(run, case_id) is None:
        return ""
    return (reviews.get(case_id, {}).get("reviewer") or "Not reviewed yet")


def on_show_institution(run, reviews, case_id):
    """Show the team's declared affiliation separately, without changing review records."""
    if find_case(run, case_id) is None:
        return ""
    author = reviews.get(case_id, {}).get("reviewer")
    if not author:
        return "Not reviewed yet"
    return REVIEWER_INSTITUTIONS.get(author.strip().casefold(), "Not specified")


def on_show_identity(run, reviews, case_id):
    return (on_show_reviewer(run, reviews, case_id), on_show_institution(run, reviews, case_id))


def review_form_values(run, reviews, case_id):
    """Plain data, safe inside a Gradio callback where component constructors are updates."""
    case = find_case(run, case_id)
    if case is None:
        return "Pending", [NOT_COUNTED], NOT_COUNTED, "", "", "", "", ""
    review = reviews.get(case_id, {})
    supported = review.get("supported_claims")
    choices = [NOT_COUNTED] + [str(number) for number in range(case["claim_count"] + 1)]
    return (decision_label(review), choices, NOT_COUNTED if supported is None else str(supported),
            review.get("notes", ""), review.get("suggestion", ""), "", *on_show_identity(run, reviews, case_id))


def on_show_form(run, reviews, case_id):
    """Fill the historical read-only form; preserve its existing return contract."""
    value = review_form_values(run, reviews, case_id)
    return value[0], gr.Dropdown(choices=value[1], value=value[2]), *value[3:]


def on_save_review(run, reviews, choice, case_id, reviewer, decision, supported, notes, suggestion):
    """Keep a valid review in memory and show it in the table; refuse invalid ones with a reason."""
    case = find_case(run, case_id)
    if case is None:
        return reviews, gr.skip(), gr.skip(), '<p class="load-error">Load a run and choose a case first.</p>'
    try:
        review = make_review(case, reviewer, decision, supported, notes, suggestion)
    except ReviewError as exc:
        return reviews, gr.skip(), gr.skip(), f'<p class="load-error">Not saved: {esc(exc)}</p>'
    reviews = {**reviews, case_id: review}
    message = (f'<p class="review-ok">Review for {esc(case_id)} kept in memory. '
               "It is not exported yet; reloading the run discards it.</p>")
    return reviews, case_table(run, reviews, choice), review_progress(run, reviews, choice), message


def on_export(run, reviews):
    """Save all reviews (scorer file) and suggestions (separate file) to a new export folder."""
    if run is None:
        return '<p class="load-error">Load a run before exporting.</p>'
    try:
        session = export_session(run, reviews)
    except (RunLoadError, ValueError, OSError) as exc:
        return f'<p class="load-error">Not exported: {esc(exc)}</p>'
    reviewed = sum(1 for review in reviews.values() if review.get("decision") is not None)
    suggestions = sum(1 for review in reviews.values() if review.get("suggestion"))
    return (f'<p class="review-ok">Exported to {esc(session)}<br>'
            f"Reviewed {reviewed} of {len(run['cases'])} cases ({len(run['cases']) - reviewed} pending); "
            f"{suggestions} human suggestion(s). The saved run was not changed.</p>")


def form_matches_saved(run, reviews, case_id, decision, supported, notes, suggestion) -> bool:
    """True when the form shows exactly this case's review in memory (or a blank Pending one)."""
    case = find_case(run, case_id)
    if case is None:
        return True
    review = reviews.get(case_id, {})
    saved_supported = review.get("supported_claims")
    return (decision == decision_label(review)
            and supported == (NOT_COUNTED if saved_supported is None else str(saved_supported))
            and (notes or "") == review.get("notes", "")
            and (suggestion or "").strip() == review.get("suggestion", ""))


def lock_updates(locked: bool):
    """While the form has unsaved edits, block navigation, loading, resuming and exporting, and say why."""
    marker = ('<p class="load-error">● Unsaved changes: click Save review or Discard changes '
              "before moving to another case, loading, resuming or exporting.</p>") if locked else ""
    enabled = not locked
    return (locked, marker, gr.Dropdown(interactive=enabled), gr.Button(interactive=enabled),
            gr.Button(interactive=enabled), gr.Button(interactive=enabled), gr.Button(interactive=enabled),
            gr.Button(interactive=enabled))


def on_form_edit(run, reviews, case_id, decision, supported, notes, suggestion):
    """Mark the form as unsaved when it differs from the review in memory."""
    return lock_updates(not form_matches_saved(run, reviews, case_id, decision, supported, notes, suggestion))


def on_unlock():
    return lock_updates(False)


def on_list_exports(run):
    """Fill the resume list with this run's earlier exports, newest first."""
    names = list_exports(run)
    return gr.Dropdown(choices=names, value=names[0] if names else None)


def on_resume(run, choice, session_name):
    """Replace the reviews in memory with a checked earlier export."""
    if run is None:
        return gr.skip(), gr.skip(), gr.skip(), '<p class="load-error">Load a run first.</p>'
    try:
        reviews = import_session(run, session_name)
    except ReviewError as exc:
        return gr.skip(), gr.skip(), gr.skip(), f'<p class="load-error">Not resumed: {esc(exc)}</p>'
    message = (f'<p class="review-ok">Resumed {len(reviews)} review(s) from {esc(session_name)}. '
               "The reviews in memory were replaced; the export folder was not changed.</p>")
    return reviews, case_table(run, reviews, choice), review_progress(run, reviews, choice), message


def build_app(default_run: str = "", *, runs_root="runs", allow_evaluation=False,
              identity_provider=None, oauth_enabled=False) -> gr.Blocks:
    from ui import review_access as access
    from ui.reviewer_accounts import require_own_run

    def identity(request):
        return identity_provider(request) if identity_provider is not None else None

    def writable(run, request):
        try:
            require_own_run(run, identity(request))
            return True
        except ReviewError:
            return False

    paths = discover_runs(runs_root, allow_evaluation=allow_evaluation)
    if default_run and default_run not in paths:
        paths.append(default_run)
    locations = {Path(path).name: path for path in paths}
    if len(locations) != len(paths):
        raise ValueError("Saved run folders must have distinct names.")
    choices = list(locations)
    selected = Path(default_run).name if default_run else (choices[0] if choices else None)

    def load_view(folder, own, request):
        try:
            run, restored, message = access.load_review(folder, locations, identity(request), own=own,
                                                        allow_evaluation=allow_evaluation)
        except (ReviewError, RunLoadError, ValueError, OSError) as exc:
            return None, f'<p class="load-error">{esc(exc)}</p>', [], gr.Dropdown(choices=[], value=None), {}
        case_ids = [case["case_id"] for case in run["cases"]]
        return (run, run_summary(run) + f'<p class="review-ok">{esc(message)}</p>',
                case_table(run, restored), gr.Dropdown(choices=case_ids, value=case_ids[0] if case_ids else None), restored)

    def load_original(folder, request: gr.Request):
        return load_view(folder, False, request)

    def load_mine(folder, request: gr.Request):
        return load_view(folder, True, request)

    def show_form(run, reviews, case_id, request: gr.Request):
        values = review_form_values(run, reviews, case_id)
        enabled = writable(run, request)
        return (gr.Radio(value=values[0], interactive=enabled),
                gr.Dropdown(choices=values[1], value=values[2], interactive=enabled),
                gr.Textbox(value=values[3], interactive=enabled), gr.Textbox(value=values[4], interactive=enabled),
                *values[5:], gr.Button(interactive=enabled), gr.Button(interactive=enabled))

    def save_view(run, reviews, choice, case_id, decision, supported, notes, suggestion, request: gr.Request):
        try:
            updated = access.save_own(run, reviews, find_case(run, case_id), identity(request),
                                      decision, supported, notes, suggestion)
        except (ReviewError, ValueError) as exc:
            return reviews, gr.skip(), gr.skip(), f'<p class="load-error">Not saved: {esc(exc)}</p>'
        return (updated, case_table(run, updated, choice), review_progress(run, updated, choice),
                '<p class="review-ok">Your review is in memory. Export to persist it separately from original reviews.</p>')

    def export_view(run, reviews, request: gr.Request):
        try:
            session = access.export_for_account(run, reviews, identity(request))
            return f'<p class="review-ok">Your review exported to {esc(session.name)}. Original reviews are unchanged.</p>'
        except (ReviewError, RunLoadError, ValueError, OSError) as exc:
            return f'<p class="load-error">Not exported: {esc(exc)}</p>'

    def list_view_exports(run, request: gr.Request):
        try:
            names = access.exports_for_view(run, identity(request))
        except (ReviewError, OSError, ValueError):
            names = []
        return gr.Dropdown(choices=names, value=names[0] if names else None)

    def resume_view(run, choice, session_name, request: gr.Request):
        if run is None:
            return gr.skip(), gr.skip(), gr.skip(), '<p class="load-error">Load a run first.</p>'
        try:
            restored = access.resume_for_view(run, session_name, identity(request))
        except (ReviewError, RunLoadError, ValueError, OSError) as exc:
            return gr.skip(), gr.skip(), gr.skip(), f'<p class="load-error">Not resumed: {esc(exc)}</p>'
        return restored, case_table(run, restored, choice), review_progress(run, restored, choice), "Saved review restored."

    def edit_lock(run, reviews, case_id, decision, supported, notes, suggestion, request: gr.Request):
        values = list(on_form_edit(run, reviews, case_id, decision, supported, notes, suggestion))
        values[7] = gr.Button(interactive=not values[0] and writable(run, request))
        return (*values, gr.Button(interactive=not values[0]))

    def unlock_view(run, request: gr.Request):
        values = list(on_unlock())
        values[7] = gr.Button(interactive=writable(run, request))
        return (*values, gr.Button(interactive=True))

    def account_message(request: gr.Request):
        account = identity(request)
        return (f"Signed in as **{esc(account.label)}**. New judgments belong only to your account." if account else
                "Not signed in. Original reviews are read-only. Sign in to start your own review.")

    with gr.Blocks(title="Saved run review", analytics_enabled=False) as review:
        gr.Markdown("# Stapfer saved run review")
        gr.Markdown(BANNER)
        gr.Markdown("**Original reviews are read-only.** A signed-in reviewer starts a separate session, "
                    "initially Pending, and exports only their own judgments. Existing answers and grades never change.")
        with gr.Row():
            gr.Button("Sign in with Hugging Face", link="/auth/huggingface/login" if oauth_enabled else None,
                      interactive=oauth_enabled)
            gr.Button("Sign out", link="/auth/logout" if oauth_enabled else None, interactive=oauth_enabled)
        if not oauth_enabled:
            gr.Markdown("**Hugging Face sign-in is not configured yet.** The operator must provide the registered "
                        "OAuth client ID. No local/mock login or manually typed name can authorize a review.")
        account_info = gr.Markdown()
        if allow_evaluation:
            gr.Markdown("**Evaluation-split review enabled explicitly.** These questions have already "
                        "been used for development. Draft references are not approved truth. "
                        "This is Q&A review, not the separate 100-document audit.")
        run_state = gr.State(None)
        reviews = gr.State({})
        dirty = gr.State(False)

        with gr.Row():
            run_path = gr.Dropdown(label="Saved run folder", choices=choices, value=selected,
                                   allow_custom_value=False, scale=4)
            load_button = gr.Button("View original reviews (read-only)", variant="primary", scale=1)
        mine_button = gr.Button("Start / resume my Hugging Face review")
        run_info = gr.HTML(label="Run", show_label=True, container=True, padding=True)
        filter_choice = gr.Radio(choices=FILTERS, value="All", label="Show")
        filter_info = gr.HTML()
        cases = gr.Dataframe(headers=TABLE_HEADERS, value=[], interactive=False, wrap=True,
                             max_height=320, label="Cases (click a row to open it)")
        with gr.Row():
            previous_button = gr.Button("◀ Previous")
            case_id = gr.Dropdown(label="Case", choices=[], value=None, scale=2)
            next_button = gr.Button("Next ▶")

        with gr.Row():
            question_panel = gr.HTML(label="Question and model answer", show_label=True, container=True, padding=True)
            reference_panel = gr.HTML(label="Draft reference", show_label=True, container=True, padding=True)
        evidence_panel = gr.HTML(label="Original evidence delivered to the model", show_label=True,
                                 container=True, padding=True)

        with gr.Accordion("Technical details (read-only, recorded files)", open=False):
            timeline = gr.HTML(label="Recorded stages in order", show_label=True, container=True, padding=True)
            artifact_choice = gr.Dropdown(choices=list(TECHNICAL_FILES), value=list(TECHNICAL_FILES)[0],
                                          label="Recorded file")
            artifact_view = gr.Textbox(label="File contents", interactive=False, lines=20, max_lines=40)

        gr.Markdown("### Human review")
        with gr.Row():
            saved_reviewer = gr.Textbox(label="Reviewer of this decision", interactive=False,
                                       info="Author stored with the displayed review; restored separately for every case.")
            saved_institution = gr.Textbox(label="Reviewer institution", interactive=False,
                                          info="Affiliation supplied by the project team, not institutional endorsement.")
        reviewer = gr.Textbox(label="Your name (required only when saving an edit)",
                             visible=False, interactive=False)
        with gr.Row():
            decision = gr.Radio(choices=list(DECISIONS), value="Pending", label="Decision", interactive=False)
            supported = gr.Dropdown(choices=[NOT_COUNTED], value=NOT_COUNTED, label="Supported claims", interactive=False)
        notes = gr.Textbox(label="Review notes", lines=2, interactive=False)
        suggestion = gr.Textbox(label="Human suggestion: corrected answer (never replaces the model answer)",
                                lines=3, interactive=False)
        with gr.Row():
            save_button = gr.Button("Save my review (in memory)", variant="primary", interactive=False)
            discard_button = gr.Button("Discard changes")
        unsaved_marker = gr.HTML()
        review_message = gr.HTML()

        gr.Markdown("### Export")
        export_button = gr.Button("Export my reviews separately", interactive=False)
        with gr.Row():
            export_choice = gr.Dropdown(choices=[], value=None, scale=3,
                                        label="Earlier exports of this run (newest first)")
            resume_button = gr.Button("Resume from this export", scale=1)
        export_message = gr.HTML()

        panels = [question_panel, evidence_panel, reference_panel]
        form = [decision, supported, notes, suggestion, review_message, saved_reviewer, saved_institution,
                save_button, export_button]
        technical = [timeline, artifact_view]
        lock = [dirty, unsaved_marker, case_id, previous_button, next_button, load_button, resume_button,
                export_button, mine_button]
        form_values = [run_state, reviews, case_id, decision, supported, notes, suggestion]
        for button, callback in [(load_button, load_original), (mine_button, load_mine)]:
            button.click(callback, [run_path], [run_state, run_info, cases, case_id, reviews]).then(
                on_filter, [run_state, reviews, filter_choice], [cases, filter_info]).then(
                on_select, [run_state, case_id], panels).then(
                show_form, [run_state, reviews, case_id], form).then(
                on_show_technical, [run_state, case_id, artifact_choice], technical).then(
                list_view_exports, [run_state], export_choice).then(
                unlock_view, [run_state], lock)
        case_id.change(on_select, [run_state, case_id], panels)
        case_id.change(on_show_technical, [run_state, case_id, artifact_choice], technical)
        artifact_choice.change(on_show_technical, [run_state, case_id, artifact_choice], technical)
        case_id.change(show_form, [run_state, reviews, case_id], form)
        save_button.click(save_view,
                          [run_state, reviews, filter_choice, case_id, decision, supported,
                           notes, suggestion],
                          [reviews, cases, filter_info, review_message]).then(
            on_show_identity, [run_state, reviews, case_id], [saved_reviewer, saved_institution]).then(
            edit_lock, form_values, lock)
        discard_button.click(show_form, [run_state, reviews, case_id], form).then(unlock_view, [run_state], lock)
        for field in [decision, supported, notes, suggestion]:
            field.input(edit_lock, form_values, lock)
        export_button.click(export_view, [run_state, reviews], export_message).then(
            list_view_exports, [run_state], export_choice)
        resume_button.click(resume_view, [run_state, filter_choice, export_choice],
                            [reviews, cases, filter_info, export_message]).then(
            show_form, [run_state, reviews, case_id], form).then(unlock_view, [run_state], lock)
        filter_choice.change(on_filter, [run_state, reviews, filter_choice], [cases, filter_info])
        cases.select(on_table_select, [dirty], case_id)
        previous_button.click(on_previous, [run_state, reviews, filter_choice, case_id], case_id)
        next_button.click(on_next, [run_state, reviews, filter_choice, case_id], case_id)
        review.load(account_message, None, account_info)
    return review
