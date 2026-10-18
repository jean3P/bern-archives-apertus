# Concise evidence answers

Version6 of `--pipeline apertus-qualified` uses the original answer schema: status, claims and
message, with text/citations per claim. It does not request the separate qualifications field
introduced by version5. That earlier version and its saved results remain available for offline
replay; they are not rewritten or treated as version6 results.

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
  --out runs/j4-development-concise-01 \
  --allow-draft-references
```

Check whether that run has already completed before executing the command. Existing paths are
never overwritten. Keep all references and the ambiguous development question unchanged. A
draft development comparison is not human-approved gold, held-out evaluation or the separate
100-document audit. No expected answers or source IDs enter runtime logic.
