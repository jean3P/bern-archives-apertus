# Saved run review guide

The review dashboard opens a **saved J4 run** and lets a person check each question: the model's answer, the evidence it received and the draft reference, side by side. You record a human decision and, if useful, a suggested corrected answer. The dashboard only reads recorded files. It does not call Apertus, search the dataset or need a GPU, and it never changes the saved run.

This is **SAVED RUN REVIEW**: recorded results, not a fresh LIVE answer and not a DEMO example.

## Before you start

- Install the project as described in the [README](../README.md) (`uv sync --locked`).
- Ask the run's owner for a private copy of a completed development run, for example `j4-development-coverage-01`, and place it in `runs/`. Saved runs and exports are ignored by Git; never commit them.
- By default only **development** runs can be opened. An explicit `--allow-evaluation` option permits review of an evaluation split that has already been used. Do not enable it for an untouched held-out test.

## Start

```bash
uv run --locked python review_app.py --run runs/j4-development-coverage-01 --port 7862
```

Open `http://127.0.0.1:7862` and click **Load**. The app listens only on your own computer and has no public share link. Use a different `--port` if 7862 is busy; the live explorer (`app.py`) uses 7860, so both can run at once. After restarting the app, click **Load** again.

To select among completed runs in a folder, including an already-used evaluation split:

```bash
uv run --locked python review_app.py --runs-root runs --allow-evaluation --port 7862
```

The selector lists immediate completed run folders, not descendants of `_archive/` or review-export folders. Choose a run and click **Load**; development and evaluation references are selected from that run's own snapshot. Twenty questions per model plus thirty per model are100 saved outputs, not100 different questions. The separate100-document dataset audit is not performed here. A manual run path still works.

If loading fails, the page clears and explains why. **Run changed or incomplete** means a file no longer matches the run's seal (`_COMPLETE.json`); ask for a fresh copy instead of editing it.

## Read a case

- **Cases table:** every case with its question, backend status, your review decision and duration. Click a row, use the **Case** list or **◀ Previous / Next ▶**.
- **Show:** filter by All, Pending, Correct, Incorrect, Uncertain or Technical error. The line above the table shows how many cases are shown and the review progress. These counts are **not a final accuracy**: pending cases are not reviewed yet.
- **Question and model answer:** the answer exactly as generated, with the backend status and message.
- **Draft reference:** the required facts and known source quotations. It is a draft for checking, not approved truth.
- **Original evidence delivered to the model:** the passages Apertus actually received, with record ID, survey question and archive reference. Spelling, accents and editorial markers such as `$` and `@` are shown as recorded. A missing page mapping is shown as *Page not verified*.
- **Technical details** (closed by default): the recorded stages in order, calls, retries, timing and tokens, and the raw recorded files, including every request to and response from the model. Field bindings, bound evidence, answer parts, holds and completeness checks are available when recorded; missing files remain Unavailable.

## Review a case

1. Enter your **name**. A decision or suggestion needs a named human reviewer.
2. Choose a **Decision**:
   - **Correct:** the answer fully answers the question and every claim is supported.
   - **Incorrect:** something is missing or wrong, even if what it says is true.
   - **Uncertain:** you cannot decide; explain why in the notes.
   - **Pending:** not reviewed yet.
3. Set **Supported claims**: how many of the answer's claims the delivered evidence really supports. This is about truth, not completeness. An answer can have all claims supported and still be Incorrect because it leaves out a requested fact.
4. Write **notes**: what is missing or wrong, and whether it was in the delivered evidence.
5. Optionally write a **Human suggestion**: a corrected answer. It is stored separately and never replaces the model answer. Keep original terms; do not invent modern equivalents.
6. Click **Save review (in memory)**. The table and counts update.

The dashboard refuses reviews its scorer would reject, and says why. For example, Correct needs every claim checked as supported, and a technically failed response cannot be Correct.

While the form has **unsaved changes**, moving to another case, loading, resuming and exporting are blocked. Click **Save review** or **Discard changes** first.

### Example

DEV-12 asks for the daily school duration **and** the two mornings-only days. An older run gives four hours but not the days, although the evidence contains *Donnerstag* and *Samstags*. That older response is incomplete. Later runs may already include both days: judge the actual selected response rather than copying the example's verdict.

## Export and resume

Reviews live only in the page until you export them, and clicking **Load** discards them.

- **Export reviews and suggestions to a new folder** writes a new folder under `runs/review-exports/`. Nothing is ever overwritten:
  - `reviews.jsonl`: one line per case with the scorer's six fields (`case_id`, `review_binding`, `reviewer`, `decision`, `supported_claims`, `notes`). Pending is `null`. It is checked with the scorer's own review loader before the export is reported.
  - `suggested-corrections.json`: the human suggestions, labelled *Human suggestion, not generated output*, with the run's seal fingerprint.
- **Resume from this export** reads an earlier export of the same run back in and replaces the reviews in the page. It refuses exports from another run, a changed run, changed answers (a different `review_binding`) and repeated cases.

Export is refused if the run's seal no longer verifies. Hand the newest export folder to the evaluation owner. Delete practice exports first so that they are not mistaken for the real review.

## What the dashboard does not do

It does not run the model, the search or the scorer, change the saved run or its references, publish anything, or turn a partial review into an accuracy figure. Final scoring is done separately by the evaluation owner from the exported `reviews.jsonl`.

## Tests

```bash
uv run --locked pytest -q tests/ui/test_run_review.py
```

The tests build small synthetic runs, labelled as fixtures, with network access blocked. They check loading and refusal rules, safe paths, escaping, the review rules, filters, export, resume and that the run's files are unchanged.
