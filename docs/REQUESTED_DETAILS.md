# Experimental requested detail answering

This optional mode is **not the recommended default**. It improves teacher-family evidence retrieval and exact quotation handling, but the complete Apertus development comparison still contains wrong field attribution and incomplete answers. The Qwen-only comparator improves the three targeted location and fee failures, while historical translation and language-quality issues remain. Keep the existing baseline until human review and final-procedure qualification.

```bash
uv run --locked python -m core.answer_cli "Your question" \
  --pipeline apertus-qualified --retrieval-mode coverage \
  --transcription-id 16 --data-dir data/derived/j2-full \
  --out runs/manual-coverage-new
```

Omit `--transcription-id` only for a named-subject question that can be resolved by the existing entity retrieval. Always choose a new output directory. The default pipeline and live application do not switch to this mode automatically.

For a **Qwen-only comparison**, configure a running OpenAI-compatible endpoint with `BERN_QWEN_BASE_URL` and the pinned `BERN_QWEN_MODEL=Qwen/Qwen3-VL-32B-Instruct`, then use:

```bash
uv run --locked python -m core.evaluate_cli run \
  --pipeline qwen-only --retrieval-mode coverage \
  --references evaluation/references/draft-v1 --split evaluation \
  --data-dir data/derived/j2-full --out runs/qwen-coverage-new \
  --allow-draft-references
```

This option uses Qwen for both routing and answering, not a hybrid. It retains the same prompts, schemas, retrieval, quote validator, formatter and per-question budgets. Model identity is checked against the selected pipeline. The already exposed thirty-question split is a development replay, even though its filename is `evaluation`. Draft references do not establish human-approved accuracy. This comparison does not change the live default or establish an eligible Apertus-powered final submission.

## Procedure

The software separates literal English/French question units, preserves explicit survey-code scope, retrieves related original records and asks focused questions to the selected model. Teacher-family evidence is located from the catalogue's teacher section, not from expected answer IDs. Raw routes and effective fields are recorded separately.

The model selects numbered source spans instead of retyping quotations. Software copies original text into citations and uses the unchanged exact-quote validator and five-field response formatter. Span selection and a valid quotation do not certify the meaning or completeness of a claim.

The whole question has a hard three-generation limit and one shared validation retry, not a new allowance per part. Some complex questions cannot fit that bound and must be simplified. Scoped routing uses at most384 output tokens and answers at most768. The explicit pipeline selects Apertus v1.5 8B or the pinned Qwen32B comparator.

An exact-date availability guard holds an age-only request before answering. Its limited numeric and English/French/German date recognizer can reject unfamiliar date formats; a recognized date is not proof of a birth-date relationship. These holds are software decisions, not model reasoning successes.

## Inspecting results

Alongside ordinary response, evidence and event files, inspect:

- `coverage_plan.json` and `coverage_route.json` when routing was needed;
- `coverage_related_fields.json` and `coverage_effective_requirements.json`;
- `coverage_answer.json`, containing each actual accepted part reply and its request position;
- `quote_translation.json`, containing software-owned spans and the normalized response;
- `coverage_type_gate.json` when the exact-date availability check holds the answer.

Known limitations include empty or overly broad field routes falling back to a full packet, answers about the wrong attribute despite valid quotes, omitted amounts, awkward translations and editorial markers in claim text. Do not count successful software checks or technical completions as question accuracy. Preserve failed runs and compare the whole procedure; never splice the best answers from different versions.
