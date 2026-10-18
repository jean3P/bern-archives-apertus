"""Stapfer evidence explorer: Jeni's interface (S1)."""

import gradio as gr

from ui.demo import load_demo_response

DEMO_BANNER = "## DEMO — display example, not a model result"


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


def on_ask(question, transcription_id):
    response = load_demo_response("answered")
    banner = DEMO_BANNER if response["mode"] == "demo" else ""
    answer_text = response["answer"] or ""
    source_text = "\n\n---\n\n".join(format_source(c) for c in response["sources"])
    return banner, answer_text, source_text


with gr.Blocks(title="Stapfer evidence explorer") as demo:
    gr.Markdown("# Stapfer evidence explorer")
    banner = gr.Markdown()

    question = gr.Textbox(label="Your question")
    transcription_id = gr.Number(label="Transcription ID (optional)", precision=0)
    ask_button = gr.Button("Ask", variant="primary")

    answer = gr.Textbox(label="Answer", interactive=False)
    source = gr.Textbox(label="Original source", interactive=False, lines=8)

    ask_button.click(
        on_ask,
        inputs=[question, transcription_id],
        outputs=[banner, answer, source],
    )

if __name__ == "__main__":
    demo.launch()