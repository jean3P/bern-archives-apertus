# Qwen evidence extraction with Apertus answers

This opt-in candidate uses **Qwen3-VL-32B-Instruct** for question interpretation and source-linked evidence extraction, then **Apertus v1.5 8B** for the final answer. It operates on the existing expert transcriptions, not images or OCR. No training, dataset rewrite, reference-answer substitution or automatic service switching is involved.

The implementation and synthetic controls are prepared but **not executed**. No hybrid quality, latency, software-pass or GPU-coexistence result exists yet. The default application/service remains Apertus-only; use `--pipeline qwen-apertus` explicitly in the CLI/evaluator. Do not merge this source into `main` or modify the live UI merely to run the development comparison.

## Stages and checks

1. Qwen receives the actual question, optional transcription scope and bounded survey catalogue. It describes one to five requested facets, their subjects, up to three relevant survey codes, bounded global keywords and material interpretation ambiguity. Software assigns facet IDs in order.
2. Existing read-only SQLite retrieval assembles original passages. Explicit codes still require a transcription. Natural and explicit-code hybrid requests both receive Qwen interpretation. No route or an empty evidence packet produces a scoped nonanswer without extraction or final generation; it does not establish archive absence.
3. Qwen extracts exactly one fact/status per facet, citing actual record IDs and exact delivered quotes. Missing, ambiguous and conflicting facets remain unresolved. Citations must respect a facet's selected survey-question route; that prevents a quote from another routed field from silently supplying it.
4. Apertus receives the original question, facets, full delivered passages and the fallible extraction checklist. Final claims name the facets they address and cite linked extracted evidence. A nonempty interpretation ambiguity or unresolved extraction cannot become an answered result.
5. Software checks facet coverage, source/quote membership and citation links, then exports the unchanged five-field application response. The normal source formatter and quote validator remain unchanged. Internal facet fields stay in separate saved receipts, not the UI response.

These are structural checks, **not semantic entailment or arithmetic verification**. A model can tag the wrong wording with a valid facet ID, choose the wrong subject in the first place, or extract an incorrect fact alongside a real quote. Human review must still judge requested-detail completeness, population, qualifications and actual support. The module's synthetic controls explicitly retain that limitation.

## Budgets and settings

| Pipeline | Normal stages | Maximum generation POST attempts | Validation retries |
| --- | --- | ---: | ---: |
| `apertus` default | Existing router when needed, then answer | 3 per question | One existing answer-validation retry |
| `qwen-apertus` opt-in | Qwen interpretation, Qwen extraction, Apertus answer | 4 per question | **One shared** validation retry across all three stages |

Hybrid token ceilings are 512 for interpretation, 1536 for extraction and 768 for final generation, temperature zero. The 18,000-character prepared-message guard, five-group/2,000-character passage/11,000-character packet bounds and source-attribution uncertainty remain. Character bounds do not establish exact model-token fit. Truncated/wrong-model/transport replies are errors, not semantic absence and not automatic retries. A long valid extraction may still exceed the next request's character guard; preserve that failure rather than silently trimming its evidence.

Use the existing Apertus settings and these independent Qwen variables:

```bash
export BERN_QWEN_BASE_URL=http://127.0.0.1:8012/v1
export BERN_QWEN_MODEL=Qwen/Qwen3-VL-32B-Instruct
export BERN_QWEN_TIMEOUT=180
```

`BERN_QWEN_API_KEY` is optional and independent of `BERN_APERTUS_API_KEY`. Neither key is logged. The exact two model IDs are checked rather than silently falling back to a smaller/different model. Actual served checkpoint identity beyond its API model name requires serving/provenance checks; the API name alone does not prove weight contents.

Both endpoints must be reachable when generation is requested. The application never starts, stops, downloads or swaps models. They may run on different hosts/GPUs. On a shared GPU, check real free memory and reserve KV-cache/workspace headroom; checkpoint sizes alone do not prove coexistence. Do not start a second large model on an already full GPU or stop unrelated jobs.

An optional owned `scripts.serve_qwen` helper supports `start`, `status` and idle-checked `stop`. It needs `BERN_QWEN_MODEL_DIR` pointing at the complete selected local checkpoint and `BERN_VLLM_IMAGE` containing an already available digest-pinned compatible image. It verifies selected config/index hashes and 14 shard files, mounts the checkpoint read-only, disables downloads, binds loopback, uses BF16/zero CPU offload/context8192/one sequence/text-only input, and defaults to a .72 GPU reservation. **It does not rehash every weight byte or establish successful startup.** Its ownership tests are authored but unexecuted. It never reconfigures Apertus or stops a different service. Private host-specific setup and any deliberately scheduled Apertus restart belong in the Obsidian runbook, not the public README.

## Commands after source and serving preparation

First run offline software controls, then the whole suite:

```bash
uv run --locked pytest -q tests/core/test_question_evidence.py tests/core/test_qwen_serving.py tests/core/test_answering.py tests/core/test_evaluation.py
uv run --locked pytest -q
```

Only after passing tests and preparing both services, inspect their model lists without generation:

```bash
curl --fail --show-error http://127.0.0.1:8010/v1/models
curl --fail --show-error http://127.0.0.1:8012/v1/models
```

Acquire a new development run, preserving all old runs:

```bash
uv run --locked python -m core.evaluate_cli run \
  --pipeline qwen-apertus \
  --references evaluation/references/draft-v1 \
  --split development \
  --data-dir data/derived/j2-full \
  --out runs/j4-development-hybrid-01 \
  --allow-draft-references
```

This explicitly makes model requests, at most **80 POST attempts for 20 questions**, not a dry run. Some questions can stop after interpretation/retrieval; 60 is the three-stage count if all 20 require every stage without repairs. There is no evaluator-level retry. Use a new output name if it exists. Compare all 20 questions, not just known failures; preserve correct nonanswers, ambiguity, unsupported claims and runtime errors. Do not run the 30-case evaluation until the candidate/reference review is frozen and approved separately.

For a deliberate single-question diagnostic, the same flag is available:

```bash
uv run --locked python -m core.answer_cli \
  "According to II.9, what is the usual daily school duration and which two days have mornings only?" \
  --pipeline qwen-apertus --transcription-id 2069 \
  --data-dir data/derived/j2-full --out runs/hybrid-question-01
```

Do not add a single-question call merely as a warm-up before the full comparison unless you intend to spend/log that additional request. The hybrid disallows `--no-query-rewrite`; use the baseline pipeline for literal-only diagnostics.

## Saved records and evaluation

The normal input, response, sources, evidence, raw events, claims, model lists and timing files remain. Additional records include `question_catalogue.json`, `question_interpretation.json` (raw structured output and software IDs), `evidence_extraction.json`, `facet_answer.json`, `qwen-serving.json` and `qwen-models.json`. All failed validation replies remain in `events.jsonl`. Prompt/source hashes, model roles and token ceilings are recorded in `implementation.json`.

The evaluator records the selected pipeline and both endpoint/model settings, pins its per-question budget and replays successful facet/extraction/final bindings offline. It preserves the usual response-bound review template and mechanical metrics. Historical manifests without a pipeline field remain Apertus-only; their three-call cap is not loosened. Original references, acquired outputs and review bindings must not be edited. The review dashboard can show the extra receipts as technical detail without changing its input/output contract.

The hybrid changes model roles **and** introduces structured facets, extraction and final-coverage checks; comparison with the earlier baseline measures the whole candidate, not the isolated causal benefit of 32B parameters. Startup, device memory, historical correctness and the separate document-audit target must be reported independently.

Official model reference: [Qwen3-VL-32B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-32B-Instruct). The model card is not evidence of accuracy on these archival questions.
