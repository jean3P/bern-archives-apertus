"""Stapfer evidence explorer: Jeni's interface (S1-S2)."""

import html
import gradio as gr

from ui.demo import load_demo_response

DEMO_BANNER = "## DEMO — display example, not a model result"

STATUS_LABELS = {
    "answered": "Answered",
    "insufficient_evidence": "Not enough evidence to answer",
    "error": "Error — the service did not respond",
}

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

def on_ask(question, transcription_id, scenario="answered"):
    try:
        response = load_demo_response(scenario)
    except Exception as exc:
        status_text = f"{STATUS_LABELS['error']}\nThe request failed: {exc}"
        return "", status_box("error", status_text), "", ""
    banner = DEMO_BANNER if response["mode"] == "demo" else ""
    status_text = format_status(response)
    answer_text = response["answer"] or ""
    source_text = "<hr>".join(format_source(c) for c in response["sources"])
    return banner, status_box(response["status"], status_text), answer_text, source_text


with gr.Blocks(title="Stapfer evidence explorer") as demo:
    gr.Markdown("# Stapfer evidence explorer")
    banner = gr.Markdown()

    question = gr.Textbox(label="Your question")
    transcription_id = gr.Number(label="Transcription ID (optional)", precision=0)
    scenario = gr.Dropdown(
        choices=["answered", "insufficient", "error"],
        value="answered",
        label="Demo scenario (testing only)",
    )
    ask_button = gr.Button("Ask", variant="primary")

    status = gr.Textbox(label="Status", interactive=False, lines=2)
    answer = gr.Textbox(label="Answer", interactive=False)
    source = gr.HTML(label="Original source", show_label=True, container=True, padding=True)

    ask_button.click(
        on_ask,
        inputs=[question, transcription_id, scenario],
        outputs=[banner, status, answer, source],
    )

if __name__ == "__main__":
    demo.launch(theme=THEME, css=CSS)