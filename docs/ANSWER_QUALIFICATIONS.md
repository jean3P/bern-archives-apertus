# Concise evidence answers

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
The original retrieval, source validator, formatter and512-token answer limit remain unchanged.
The default `apertus` pipeline remains separate and unchanged.

Only focused checks are needed, not the entire test suite:

```bash
uv run --locked pytest -q tests/core/test_answer_qualifications.py
```

A development comparison requires a new output directory and makes real model requests:

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
