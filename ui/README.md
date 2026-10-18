# Dyane's UI area

Create `app.py` at the project root and UI-only helpers here on branch `sister/ui`. Jean owns `core/`, `scripts/`, `contracts.py`, configuration and the dependency lock. Ask him before changing those files.

Start with `fixtures/ui/*.demo.json`: show question input, an answer area, original source cards, archive references, and visible insufficient/error states. Label every fixture response DEMO. These are not model results. Do not invent a page when `pdf_page_index` is null. Render original archival text as plain text, preserving spelling and markers.

At integration, call `core.service.search_records` and `core.service.answer_question` using `contracts.py`. They deliberately raise until Jean implements J2/J3. A reachable Apertus health endpoint is not yet archival question answering.

Run `uv sync --locked`, `uv run pytest tests/ui tests/test_contracts.py`, and later `uv run python app.py` once you create the app. Keep browser access local/private, with no public Gradio sharing. Write user instructions in `docs/USER_GUIDE.md`.
