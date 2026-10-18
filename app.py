"""Stapfer evidence explorer: Jeni's interface (S1-S2)."""

import html
import math
import gradio as gr

from contracts import validate_response
from core import service
from ui.demo import load_demo_response

DEMO_BANNER = "## DEMO — display example, not a model result"
LIVE_BANNER = "## LIVE — Apertus answers from retrieved archival evidence"

STATUS_LABELS = {
    "answered": "Answered",
    "insufficient_evidence": "Not enough evidence to answer",
    "error": "Error — no answer was produced",
}


class InputValidationError(ValueError):
    """An authored input hint that is safe to display to the user."""


THEME = gr.themes.Default().set(
    block_title_text_size="*text_lg",
    block_title_text_weight="600",
    input_text_size="20px",
)

CSS = """
.status-box textarea {
    font-weight: 600;
    border-left: 6px solid transparent !important;
}
.status-answered textarea {
    background: #e8f5e9 !important;
    color: #1b5e20 !important;
    border-left-color: #2e7d32 !important;
}
.status-insufficient_evidence textarea {
    background: #fff8e1 !important;
    color: #6d4c00 !important;
    border-left-color: #f9a825 !important;
}
.status-error textarea {
    background: #fdecea !important;
    color: #8e1c1c !important;
    border-left-color: #c62828 !important;
}
.source-card,
.source-card div {
    font-size: 18px !important;
    font-weight: 500;
    line-height: 1.6;
}
.source-card strong {
    font-size: 18px !important;
    font-weight: 600;
}
.source-original {
    font-size: 19px;
    margin-bottom: 0.8em;
    white-space: pre-wrap;
}
"""

def format_source(card: dict) -> str:
    """Original passage plus its IDs as HTML; every data value is escaped."""
    page = card["pdf_page_index"]
    fields = [
        ("Record", card["record_id"]),
        ("Transcription", card["transcription_id"]),
        ("Question", card["question_number"] or "unknown"),
        ("Archive reference", card["archive_reference"] or "unknown"),
        ("Page", "Page not verified" if page is None else page),
    ]
    rows = "".join(
        f"<div><strong>{name}:</strong> {html.escape(str(value))}</div>"
        for name, value in fields
    )
    original = html.escape(card["text_original"])
    return f'<div class="source-card"><p class="source-original">{original}</p>{rows}</div>'

def format_status(response: dict) -> str:
    """Human-readable status plus the response's explanation, if any."""
    label = STATUS_LABELS[response["status"]]
    if response["message"]:
        return f"{label}\n{response['message']}"
    return label

def status_box(status: str, text: str):
    """Status text plus a CSS class that colours it by status."""
    return gr.Textbox(value=text, elem_classes=["status-box", f"status-{status}"])

def parse_transcription_id(value):
    """Gradio may supply integral floats; never truncate a fractional scope."""
    if value is None or isinstance(value, str) and not value.strip():
        return None
    if isinstance(value, str) and value.strip().isdecimal() and len(value.strip()) <= 19:
        value = int(value.strip())
    if (type(value) not in (int, float) or not 1 <= value <= 2**63 - 1
            or not math.isfinite(value) or value != int(value)):
        raise InputValidationError(
            "Enter a positive whole transcription ID (for example, 16), "
            "or leave it blank to search without a transcription filter."
        )
    return int(value)


def clear_response(mode="live"):
    return (DEMO_BANNER if mode == "demo" else LIVE_BANNER,
            status_box("working", "Working…"), "", "")


def on_mode_change(mode):
    banner, _, answer, source = clear_response(mode)
    return (gr.Dropdown(interactive=mode == "demo"), banner,
            status_box("ready", "Ready"), answer, source)


def on_ask(question, transcription_id, scenario="answered", mode="demo"):
    """DEMO never calls the model; LIVE never substitutes a fixture on failure."""
    try:
        if mode == "demo":
            response = load_demo_response(scenario)
        elif mode == "live":
            if not isinstance(question, str) or not question.strip() or len(question) > 2000:
                raise InputValidationError("Enter a question of 1–2000 characters.")
            response = service.answer_question(question, parse_transcription_id(transcription_id))
        else:
            raise InputValidationError("Choose LIVE or DEMO mode.")
        validate_response(response)
        if response["mode"] != mode:
            raise ValueError("Response mode does not match the selected mode.")
        banner = DEMO_BANNER if mode == "demo" else LIVE_BANNER
        status_text = format_status(response)
        answer_text = response["answer"] or ""
        source_text = "<hr>".join(format_source(c) for c in response["sources"])
        return banner, status_box(response["status"], status_text), answer_text, source_text
    except InputValidationError as exc:
        banner = DEMO_BANNER if mode == "demo" else LIVE_BANNER
        status_text = f"{STATUS_LABELS['error']}\n{exc}"
        return banner, status_box("error", status_text), "", ""
    except Exception as exc:
        detail = str(exc) if mode == "demo" else "Please try again or ask the operator to check the service configuration."
        status_text = f"{STATUS_LABELS['error']}\nThe request failed: {detail}"
        banner = DEMO_BANNER if mode == "demo" else LIVE_BANNER
        return banner, status_box("error", status_text), "", ""


with gr.Blocks(title="Stapfer evidence explorer", analytics_enabled=False) as demo:
    gr.Markdown("# Stapfer evidence explorer")
    banner = gr.Markdown(LIVE_BANNER)

    mode = gr.Radio(choices=["live", "demo"], value="live", label="Mode")
    question = gr.Textbox(label="Your question")
    transcription_id = gr.Textbox(
        label="Transcription ID (optional)", value="", placeholder="e.g. 16, or leave blank",
        info="Leave blank for no transcription filter. Example: 16 for the Hörndli transcription.",
    )
    scenario = gr.Dropdown(
        choices=["answered", "insufficient", "error"],
        value="answered",
        label="Demo scenario (testing only)",
        interactive=False,
    )
    ask_button = gr.Button("Ask", variant="primary")

    status = gr.Textbox(label="Status", interactive=False, lines=2)
    answer = gr.Textbox(label="Answer", interactive=False)
    source = gr.HTML(label="Original source", show_label=True, container=True, padding=True)

    mode.change(on_mode_change, inputs=[mode],
        outputs=[scenario, banner, status, answer, source], queue=False, api_name=False)
    ask_button.click(clear_response, inputs=[mode], outputs=[banner, status, answer, source],
        queue=False, api_name=False).then(
        on_ask,
        inputs=[question, transcription_id, scenario, mode],
        outputs=[banner, status, answer, source],
        api_name="ask",
    )

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", share=False, theme=THEME, css=CSS)
