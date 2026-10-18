# Concise evidence answers

**Frozen development candidate, not a validated release.** The completed version6.1 comparison
processes 20/20 questions with 23 requests and no retries. Separate assistant review finds 18 satisfactory,
one incorrect under the unchanged family rubric and one uncertain historical-word gloss. Keep
human review distinct from software checks; references, held-out evaluation and document audit
still require their own review. The original default and UI remain unchanged.

Two subsequent correction attempts were rejected. Stronger subject/original-term instructions
completed20 questions but reduced assistant-satisfactory results from18 to16. Two additional
parent-context/source-parenthetical probes still selected the wrong population or falsely said
the requested term was unspecified after repair. Both remaining defects are therefore open.
Runtime and tests have been restored exactly to version6.1; rejected commits and raw results
remain in history. Do not rerun the failed prompts or count schema validation as semantic repair.

Version6.1 of `--pipeline apertus-qualified` uses the original answer fields: status, claims and
message, with text/citations per claim. Its decoder requires message to be empty for answered
results, so substantive answer content cannot be placed in that uncited field. Insufficient-
evidence replies retain empty claims and a nonempty explanatory message. It does not request
the separate qualifications field introduced by version5. Saved version5 and version6 replies
retain their original offline replay behavior and are never rewritten as version6.1 results.

This candidate replaces the answer instructions with a shorter direct-answer prompt. It asks
for all requested details and genuine exceptions, original wording even when unfamiliar, exact
quotations covering each claim, no metadata in prose, and transcription-scoped attribution.
No extra interpretation stage, model call, repair allowance or answer substitution is added.
The original retrieval, source validator, formatter and 512-token answer limit remain unchanged.
The default `apertus` pipeline remains separate and unchanged.

Only focused checks are needed, not the entire test suite:

```bash
uv run --locked pytest -q tests/core/test_answer_qualifications.py
```

The following comparison has already completed. Do not rerun into its existing output directory.
Any separately authorized future comparison needs a deliberately chosen new path:

```bash
uv run --locked python -m core.evaluate_cli run \
  --pipeline apertus-qualified \
  --references evaluation/references/draft-v1 \
  --split development \
  --data-dir data/derived/j2-full \
  --out runs/j4-development-concise-02 \
  --allow-draft-references
```

Check whether that run has already completed before executing the command. Existing paths are
never overwritten. Keep all references and the ambiguous development question unchanged. A
draft development comparison is not human-approved gold, held-out evaluation or the separate
100-document audit. No expected answers or source IDs enter runtime logic.
