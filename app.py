"""Stapfer evidence explorer: Jeni's interface (S1-S2)."""

import gradio as gr

from ui.demo import load_demo_response

DEMO_BANNER = "## DEMO — display example, not a model result"

STATUS_LABELS = {
    "answered": "Answered",
    "insufficient_evidence": "Not enough evidence to answer",
    "error": "Error — the service did not respond",
}

def format_source(card: dict) -> str:
    """Original passage plus its IDs, as plain text."""
    page = card["pdf_page_index"]
    page_text = "Page not verified" if page is None else str(page)
    return (
        f"{card['text_original']}\n\n"
        f"Record: {card['record_id']}\n"
        f"Transcription: {card['transcription_id']}\n"
        f"Question: {card['question_number'] or 'unknown'}\n"
        f"Archive reference: {card['archive_reference'] or 'unknown'}\n"
        f"Page: {page_text}"
    )

def format_status(response: dict) -> str:
    """Human-readable status plus the response's explanation, if any."""
    label = STATUS_LABELS[response["status"]]
    if response["message"]:
        return f"{label}\n{response['message']}"
    return label

def on_ask(question, transcription_id, scenario="answered"):
    try:
        response = load_demo_response(scenario)
    except Exception as exc:
        status_text = f"{STATUS_LABELS['error']}\nThe request failed: {exc}"
        return "", status_text, "", ""
    banner = DEMO_BANNER if response["mode"] == "demo" else ""
    status_text = format_status(response)
    answer_text = response["answer"] or ""
    source_text = "\n\n---\n\n".join(format_source(c) for c in response["sources"])
    return banner, status_text, answer_text, source_text


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
    source = gr.Textbox(label="Original source", interactive=False, lines=8)

    ask_button.click(
        on_ask,
        inputs=[question, transcription_id, scenario],
        outputs=[banner, status, answer, source],
    )

if __name__ == "__main__":
    demo.launch()