"""Saved-run review screen (S5): read-only display of recorded development cases."""

import html
import json

import gradio as gr

from ui.review_records import (DECISIONS, NOT_COUNTED, ReviewError, RunLoadError, load_case_file,
                               load_references, load_run, make_review)


BANNER = "## SAVED RUN REVIEW — recorded development results, not a fresh LIVE answer"

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
    """Error responses, unattempted cases and definitive failures."""
    return (case.get("observed_status") == "error" or not case.get("attempted", True)
            or bool(case.get("definitive_failure")))


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


def on_table_select(evt: gr.SelectData):
    """Clicking any cell of a row selects that row's case."""
    return evt.row_value[0]


def on_load(run_path):
    """Load and verify a run; on failure clear everything and explain why."""
    try:
        run = load_run(run_path)
        run["references"] = load_references(run["directory"])
    except (RunLoadError, ValueError, OSError) as exc:
        message = f'<p class="load-error">Could not load run: {esc(exc)}</p>'
        return None, message, [], gr.Dropdown(choices=[], value=None), {}
    case_ids = [case["case_id"] for case in run["cases"]]
    first = case_ids[0] if case_ids else None
    return run, run_summary(run), case_table(run), gr.Dropdown(choices=case_ids, value=first), {}


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


def on_show_form(run, reviews, case_id):
    """Fill the review form with this case's review in memory, or a fresh Pending one."""
    case = find_case(run, case_id)
    if case is None:
        return "Pending", gr.Dropdown(choices=[NOT_COUNTED], value=NOT_COUNTED), "", "", ""
    review = reviews.get(case_id, {})
    supported = review.get("supported_claims")
    choices = [NOT_COUNTED] + [str(number) for number in range(case["claim_count"] + 1)]
    return (decision_label(review),
            gr.Dropdown(choices=choices, value=NOT_COUNTED if supported is None else str(supported)),
            review.get("notes", ""), review.get("suggestion", ""), "")


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


def build_app(default_run: str = "") -> gr.Blocks:
    with gr.Blocks(title="Saved run review", analytics_enabled=False) as review:
        gr.Markdown("# Stapfer saved run review")
        gr.Markdown(BANNER)
        run_state = gr.State(None)
        reviews = gr.State({})

        with gr.Row():
            run_path = gr.Textbox(label="Saved run folder", value=default_run, scale=4)
            load_button = gr.Button("Load", variant="primary", scale=1)
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
        reviewer = gr.Textbox(label="Reviewer name (required for a decision)")
        with gr.Row():
            decision = gr.Radio(choices=list(DECISIONS), value="Pending", label="Decision")
            supported = gr.Dropdown(choices=[NOT_COUNTED], value=NOT_COUNTED, label="Supported claims")
        notes = gr.Textbox(label="Review notes", lines=2)
        suggestion = gr.Textbox(label="Human suggestion: corrected answer (never replaces the model answer)",
                                lines=3)
        save_button = gr.Button("Save review (in memory)", variant="primary")
        review_message = gr.HTML()

        panels = [question_panel, evidence_panel, reference_panel]
        form = [decision, supported, notes, suggestion, review_message]
        technical = [timeline, artifact_view]
        load_button.click(on_load, [run_path], [run_state, run_info, cases, case_id, reviews]).then(
            on_filter, [run_state, reviews, filter_choice], [cases, filter_info]).then(
            on_select, [run_state, case_id], panels).then(
            on_show_form, [run_state, reviews, case_id], form).then(
            on_show_technical, [run_state, case_id, artifact_choice], technical)
        case_id.change(on_select, [run_state, case_id], panels)
        case_id.change(on_show_technical, [run_state, case_id, artifact_choice], technical)
        artifact_choice.change(on_show_technical, [run_state, case_id, artifact_choice], technical)
        case_id.change(on_show_form, [run_state, reviews, case_id], form)
        save_button.click(on_save_review,
                          [run_state, reviews, filter_choice, case_id, reviewer, decision, supported,
                           notes, suggestion],
                          [reviews, cases, filter_info, review_message])
        filter_choice.change(on_filter, [run_state, reviews, filter_choice], [cases, filter_info])
        cases.select(on_table_select, None, case_id)
        previous_button.click(on_previous, [run_state, reviews, filter_choice, case_id], case_id)
        next_button.click(on_next, [run_state, reviews, filter_choice, case_id], case_id)
    return review