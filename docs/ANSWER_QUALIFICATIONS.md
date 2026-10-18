# Visible answer qualifications

**Measured development candidate, not promoted.** The completed 20-question run processes 19 cases
and fixes two omissions, but adds one source-ID formatting failure and questionable qualification
wording. Keep the original default. Expected-detail coverage is not full-answer correctness.

`--pipeline apertus-qualified` keeps the baseline retrieval path and adds one string field,
`qualifications`, to each generated claim. The software displays it after that claim's text.
Both pieces must be supported by the same exact citations and fit the existing 600-character
claim limit. An exact quotation still does not establish semantic support automatically.

No separate question-interpretation call, facet IDs, substring matching, extraction model or
new repair allowance is added. Explanatory messages are allowed as in the original contract.
Insufficient-evidence replies still use empty claims and a meaningful message. The original
source validator/formatter, request/evidence bounds and 512-token answer cap stay unchanged.
The original `apertus` default and rejected `apertus-facets` experiment remain separate.

This candidate does not fix ambiguous questions or missing retrieval by construction. It
contains no expected answers, evaluation source IDs or reference-specific substitutions.
Evaluate every development case, including nonanswers, before promoting it.

Only the small changed contract checks are needed for this comparison:

```bash
uv run --locked pytest -q tests/core/test_answer_qualifications.py
```

The comparison below has already run. Do not rerun into its existing output directory. Any future
comparison needs a deliberately chosen new path and its own recorded code version:

```bash
uv run --locked python -m core.evaluate_cli run \
  --pipeline apertus-qualified \
  --references evaluation/references/draft-v1 \
  --split development \
  --data-dir data/derived/j2-full \
  --out runs/j4-development-qualifications-01 \
  --allow-draft-references
```

Keep original results and references unchanged. Draft development results are not human-approved
gold, held-out validation or the separate 100-document audit. Existing output paths are never
overwritten. Do not repeat an already completed command solely because it appears in this guide.
