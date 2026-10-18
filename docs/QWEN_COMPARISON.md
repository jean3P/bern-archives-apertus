# Qwen only development comparison

`--pipeline qwen-only` uses Qwen3-VL-32B-Instruct for both catalogue routing and cited
answer generation. It is an explicit comparator, not the `qwen-apertus` hybrid and not
the live application's default. No image inputs or extra extraction stage are used.

The comparison retains the Apertus concise-answer contract: identical routing and answer
instructions, conditional JSON schema, source validator, formatter, evidence limits,
180-token routing ceiling, 512-token answer ceiling and one shared answer-validation retry
with at most three generation requests per question. The configured and returned model
identities must match Qwen; a mismatched Apertus endpoint is rejected before generation.
Original data, reference questions and expected facts remain unchanged. Expected answers
and source IDs are never supplied to routing or answer generation.

Configure an already running, suitable Qwen server independently:

```bash
export BERN_QWEN_BASE_URL=http://127.0.0.1:8012/v1
export BERN_QWEN_MODEL=Qwen/Qwen3-VL-32B-Instruct
export BERN_QWEN_TIMEOUT=120
```

The 20-question development comparison uses the existing evaluator and records every
actual request, raw reply, evidence packet, failure and retry. Always choose a new output
directory; never delete previous results to rerun a command. The separate 30-question
evaluation and document audit are not part of this comparator.

An end-to-end improvement can come from routing, generation or both. Compare retrieved
and delivered evidence before attributing a particular answer change to generation.
For identical evidence packets, the same logical prompts/schema help isolate the tested
checkpoint's answering behavior. Native model templates/tokenizers still differ.
Qwen32B versus Apertus8B is a checkpoint comparison, not proof that parameter count alone
caused a difference. Human semantic review remains separate from automatic citation checks.

The first development comparison has completed in `runs/j4-development-qwen-only-01`:
20 technical completions, 23 normal replies, zero retries and 77.631 seconds summed question
time. Both original family-routing and historical-term cases improve. Conservative assistant
review finds 18 satisfactory cases and two translation flags, not a perfect score or a clean
aggregate win over the saved Apertus candidate's 18 satisfactory/one incorrect/one uncertain.
The owned Apertus service was restored after the sequential test. Do not reacquire into the
existing directory; inspect its report instead:

```bash
less runs/j4-development-qwen-only-01/report.md
```

Full-precision models may need sequential serving. Pause only an explicitly owned idle
service, retain failure logs, and restore its original profile after the comparison.
Do not stop unrelated workloads or change the live default. The Bern challenge permits
other model comparisons but describes the submitted pipeline as powered by Apertus.
