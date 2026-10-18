"""Saved-run review screen (S5): read-only display of recorded development cases."""

import html

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


def case_table(run, reviews=None) -> list:
    """One row per recorded case, in run order; nothing is filtered out."""
    reviews = reviews or {}
    table = []
    for case in run["cases"]:
        seconds = case.get("total_seconds")
        table.append([
            case["case_id"],
            case["input"]["question"],
            case.get("observed_status") or "not attempted",
            decision_label(reviews.get(case["case_id"])),
            "Not measured" if seconds is None else round(seconds, 2),
        ])
    return table


def step_case(run, case_id, offset):
    """Previous/next case ID, staying within the first and last case."""
    if run is None or not run["cases"]:
        return None
    case_ids = [case["case_id"] for case in run["cases"]]
    position = case_ids.index(case_id) if case_id in case_ids else 0
    return case_ids[max(0, min(len(case_ids) - 1, position + offset))]


def on_previous(run, case_id):
    return step_case(run, case_id, -1)


def on_next(run, case_id):
    return step_case(run, case_id, +1)


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


def on_save_review(run, reviews, case_id, reviewer, decision, supported, notes, suggestion):
    """Keep a valid review in memory and show it in the table; refuse invalid ones with a reason."""
    case = find_case(run, case_id)
    if case is None:
        return reviews, gr.Dataframe(), '<p class="load-error">Load a run and choose a case first.</p>'
    try:
        review = make_review(case, reviewer, decision, supported, notes, suggestion)
    except ReviewError as exc:
        return reviews, case_table(run, reviews), f'<p class="load-error">Not saved: {esc(exc)}</p>'
    reviews = {**reviews, case_id: review}
    message = (f'<p class="review-ok">Review for {esc(case_id)} kept in memory. '
               "It is not exported yet; reloading the run discards it.</p>")
    return reviews, case_table(run, reviews), message


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
        load_button.click(on_load, [run_path], [run_state, run_info, cases, case_id, reviews]).then(
            on_select, [run_state, case_id], panels).then(
            on_show_form, [run_state, reviews, case_id], form)
        case_id.change(on_select, [run_state, case_id], panels)
        case_id.change(on_show_form, [run_state, reviews, case_id], form)
        save_button.click(on_save_review,
                          [run_state, reviews, case_id, reviewer, decision, supported, notes, suggestion],
                          [reviews, cases, review_message])
        cases.select(on_table_select, None, case_id)
        previous_button.click(on_previous, [run_state, case_id], case_id)
        next_button.click(on_next, [run_state, case_id], case_id)
    return review