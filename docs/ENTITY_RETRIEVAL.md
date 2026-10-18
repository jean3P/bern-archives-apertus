# Entity aware retrieval

This opt-in mode identifies a named survey account before retrieving its requested answers. It keeps the existing concise Apertus answering prompt, source validator, formatter, three-request ceiling and one answer-validation retry. It does not change the default app or require a new database, embedding model or dependency.

## Use

From the repository root, with the existing dataset and model connection configured:

```bash
uv run --locked python -m core.answer_cli \
  "Which district does the school at Bisicken belong to?" \
  --pipeline apertus-qualified \
  --retrieval-mode entity \
  --data-dir data/derived/j2-full \
  --out runs/manual-entity-01
```

Always choose a new output folder. The example is a development case, not an untouched accuracy test. Inspect the returned answer, sources and warnings; a valid quotation is not independent semantic verification.

The evaluator accepts the same `--retrieval-mode entity` flag. Using exposed evaluation questions to improve retrieval makes subsequent runs development replays, even if the original reference file is named `evaluation-questions.jsonl`. Keep references marked draft until genuinely reviewed.

## Retrieval procedure

1. Preserve existing behavior for an explicitly scoped transcription or an unscoped explicit-question-code request.
2. For an archive-wide natural question, request named entities and requested catalogue fields in one bounded routing call.
3. If the model omits entity names, preserve that raw prediction and separately find literal question spans in primary place/person identity answers. Generic query/catalogue words cannot identify a subject alone. Case and accent normalization is search-only, not verification of historical aliases.
4. Require a unique intersection of the directly witnessed transcription candidates. Do not pick the first match or use a neighbouring-school mention as ownership evidence.
5. Retrieve requested answer fields through the existing transcription and question relationships. Include the subject-identity evidence in the packet. Retain every original ID and attribution warning.
6. Hold if scope is ambiguous, a requested field has no usable text, or complete identity/field records exceed the unchanged packet limits. Such a hold is not proof that information is absent from the archive.
7. Generate the cited answer with the unchanged concise answer contract.

The declared field checklist comes from the router; it is not an independent guarantee that the model interpreted every requested detail correctly. Same-transcription membership also does not establish exact ownership by a particular school or teacher when the source describes several.

## Records

- `retrieval_plan.json`: original model output, including empty entity lists.
- `effective_entity_plan.json`: explicit effective plan for the opt-in global route.
- `entity_selection.json`: lexical fallback, identity witnesses, candidates, selected scope, requested fields, omissions and holds.
- `retrieved_sources.json` and `evidence.json`: the actual sources and delivered packet.
- Existing request/response events and answer records remain unchanged in format.

Version 1's empty-name failure remains a separate development run. Version 2 adds the literal-name fallback without changing its model prompt or schema. Neither version permits expected benchmark answers or source IDs as runtime selectors.

## Qualification and limits

The focused synthetic checks cover useful linked retrieval, duplicate names, conflicting anchors, neighbouring-school mentions, empty/missing names, null/truncated evidence, literal fallback, preserved attribution warnings and the shared answer retry. They are not question-accuracy measurements.

The measured 30-question development replay improves reference hit@5 from 20/24 to 24/24 and full reference delivery from 18/24 to 22/24. Four archive-wide answers recover; six other inspected problems remain in role routing, quotations, answer completeness and requested answer type. Human semantic scoring and the separate document audit remain pending. No default promotion follows from the replay.

Literal matching can miss spellings not shared between the question and primary identity passages. Ambiguous names, multiple entities, fields absent from the catalogue and long evidence packets can remain held. Broader fuzzy or multilingual semantic matching requires separate evaluation; it must not silently turn a spelling resemblance into verified identity.
