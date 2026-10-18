# Apertus only per part answering

**Rejected development candidate.** The completed20-question comparison produced7 answers and
13 processing errors,52 requests and103.794 seconds, versus20 technical completions,23 requests
and40.737 seconds for the coverage-only baseline. Keep `--pipeline apertus` as the default. Do not
merge this experiment or treat its passing software checks as evidence of better answers.

Select `--pipeline apertus-facets` to test explicit question parts without Qwen. The existing
`apertus` default remains the earlier baseline, and the hybrid stays inactive unless explicitly
selected. No model/service restart, dependency change, data rebuild or UI change is required.

Apertus first identifies up to five requested parts with explicit subjects and up to three
survey-code routes. Each request is a verbatim user-question span; explicit codes restrict the
allowed routes. A clear interpretation uses JSON null, not a free-text claim of no ambiguity.
It then receives the original retrieved evidence and returns one cited answer
per part, with meaning-changing qualifications in a separate field. Software includes those
qualifications in the displayed answer, validates exact quotes and per-part survey-code links,
and rejects missing/duplicated parts. Missing evidence or material ambiguity remains unresolved.
The normalized five-field response and original source formatter/quote validator are unchanged.

No evaluation facts, expected IDs or case-specific historical answers enter this runtime.
Structural part completeness is not semantic correctness: the model can still miss a facet during
interpretation, select the wrong subject or attach a valid quote to incorrect wording. Human review
is still required. Do not silently change an ambiguous reference question after seeing outputs.

There are at most three generation POST attempts and one shared validation retry across interpretation
and answering. Token ceilings are512/1024, temperature zero; existing evidence/request bounds stay.
All raw replies and validation failures are recorded, with `question_interpretation.json`,
`part_answers.json` and normalized `validated_claims.json`. No extra extraction model stage is used.

The evaluator checks the Apertus model endpoint before beginning questions, so an unavailable
service creates a preparation failure rather than20 repeated connection failures. Offline scoring
replays the part bindings and preserves the usual response-bound review format.

The completed development comparison used the following command. Its output already exists;
do not rerun into that directory. Reproduction requires a deliberately chosen new output path.

```bash
uv run --locked python -m core.evaluate_cli run \
  --pipeline apertus-facets \
  --references evaluation/references/draft-v1 \
  --split development \
  --data-dir data/derived/j2-full \
  --out runs/j4-development-apertus-parts-02 \
  --allow-draft-references
```

This makes actual model requests, at most60 for20 questions. Compare all cases against the saved
coverage-only run, not just the known failures. Keep original runs/references unchanged. This is
a draft development comparison, not held-out validation, human-approved gold or a document audit.
Startup/serving readiness is not question accuracy. The100-document audit remains separate.

The first `j4-development-apertus-parts-01` comparison was stopped and retained after repeated
interpretation failures. Version4.1 constrains the requests to the user's actual wording and
uses nullable ambiguity. Do not overwrite or report the stopped run as a complete model benchmark.

Targeted offline checks for these changed contracts live in `tests/core/test_facet_answering.py`;
running the entire software suite is not necessary for this bounded comparison. Do not describe
unexecuted controls or a prior full-suite result as qualification of this changed candidate.
