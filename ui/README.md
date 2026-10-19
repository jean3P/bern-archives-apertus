# Application interfaces

The root `app.py` serves the LIVE evidence explorer through `core.service` and `contracts.py`. The separate `review_app.py` displays immutable recorded runs and saves account-specific review exports. UI helpers live here; answering and retrieval remain in `core/`.

`fixtures/ui/*.demo.json` contains labelled DEMO fixtures, not model results. Display original archival text as plain text with spelling and markers preserved. When `pdf_page_index` is null, show that the page is unverified rather than inventing a page.

Only a deliberate LIVE request generates a fresh model answer. Loading a saved review does not call the model; a successful model health check is not a question-accuracy measurement.

Use the root [README](../README.md) for launch commands and the [technical guide](../docs/stapfer-technical-guide.pdf) for architecture, model inputs and review semantics. Keep browser access local/private, with no public Gradio sharing. Export reviews before reloading or restarting.
