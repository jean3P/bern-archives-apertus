# Experimental field bound answering

The opt-in `bound` mode preserves the complete original question, assigns source fields to requested details, and answers those details together. The default service and UI are unchanged. Choosing this mode does not establish historical accuracy or select a final challenge submission.

## Evidence and answer checks

- A scoped detail has one catalogue field or an explicit unresolved binding. An empty binding never expands to all retrieved passages. Named-entity retrieval retains its existing unique-scope procedure and may bind a combined question to several requested fields.
- Routing selects where a fact would be recorded in the catalogue; it does not certify that an archival answer exists. The original and French survey definitions accompany the bound passages.
- When the user explicitly names several survey codes, their actual passages are retrieved before binding. A field title alone may be too narrow to describe everything the historical answer contains. This uses the supplied scope, not benchmark source IDs or expected answers.
- Source-code introductions and trailing scope clauses are not extra answer requirements. The original user question itself is never rewritten.
- Every requested detail must have a separate keyed answer. Its citation choices are restricted to records from its bound field, even when identical passages occur under several fields.
- Software copies original quotation text and applies the existing source-ID, exact-quote and response-format checks. A question echo, missing answer part or citation from another field is rejected.
- An exact-date request cannot be answered from an age alone. A requested verified PDF page index requires actual mapping metadata; an age or editorial page marker is not a substitute.
- For explicitly complete fee schedules, software derives currency amounts and period terms from the delivered source. The combined answer must retain those amounts and period terms without adding unsupported amounts. Equivalent decimal/fraction notation is accepted; currency conversion is not performed.

The fee check is deliberately limited: it checks numeric/unit and period-word conservation, not whether each amount has been assigned to the correct population or period. Nonnumeric completeness, translation and historical interpretation still require semantic review. Correctly formatted citations are not an entailment certificate.

Scoped routing has a 384-token ceiling and the joint answer a 1,024-token ceiling. The entire question retains at most three generation requests and one shared validation retry. An unresolved binding is held rather than repeatedly repaired into certainty.

## Running a comparison

Ensure the selected pinned model is already available at its configured endpoint. Do not start two large servers on a shared device without checking capacity and ownership.

```bash
uv run --locked python -m core.evaluate_cli run \
  --pipeline apertus-qualified --retrieval-mode bound \
  --references evaluation/references/draft-v1 --split evaluation \
  --data-dir data/derived/j2-full --out runs/bound-apertus-new \
  --allow-draft-references
```

For the separate Qwen-only comparator, configure `BERN_QWEN_BASE_URL` and `BERN_QWEN_MODEL=Qwen/Qwen3-VL-32B-Instruct`, then:

```bash
uv run --locked python -m core.evaluate_cli run \
  --pipeline qwen-only --retrieval-mode bound \
  --references evaluation/references/draft-v1 --split evaluation \
  --data-dir data/derived/j2-full --out runs/bound-qwen-new \
  --allow-draft-references
```

Use `--split development` with a different new output directory for the existing twenty-question retention set. Never reuse a completed output path. The thirty-question split is already exposed development data, even though it is named `evaluation`; draft-reference use is not human approval.

Inspect `binding_route.json`, `binding_plan.json`, `binding_evidence.json`, `binding_completeness.json`, `binding_answer.json` and any `binding_hold.json`, alongside the original request/response events. Source-derived checklists are not benchmark answer tables. No expected answer values or case/source-ID lookup maps are part of the runtime.
