# Bern Archives with Apertus

An evidence-preserving pipeline and small search/answer demonstrator for the University of Bern's **Deciphering Archives with Apertus** challenge, using the edited Stapfer school-survey data.

## Status

J1 provides the uv project, shared response types, demo fixtures and configurable Apertus client. **J2's full user build/verify passed:** 2,250 transcriptions and 92,524 answer rows exported, 92,336 nonblank answers indexed, and a successful filtered source query. See the [dataset commands](docs/J2.md). **J3's backend baseline is closed:** the user reported 90 passing software tests, correct explicit/natural-language answers about the same location fact and an actual empty-route unsupported-question nonanswer. Earlier failures are preserved. **M1's live screen-to-evidence baseline passed:** 70 selected software tests plus fresh browser answer/nonempty-evidence abstention checks; see [M1 instructions](docs/M1.md). J4 has a recorded 20-question development run; its 30-case evaluation and independent document audit remain pending. See the [evaluation commands and review rubric](docs/J4.md). No general historical-accuracy, 80% correctness or inexpensive-hardware benchmark is claimed.

## Quick start

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and authenticate with an account that has access to the private repository.

```bash
git clone https://github.com/jean3P/bern-archives-apertus.git
cd bern-archives-apertus
uv sync --locked
uv run pytest -q
```

Python 3.11.16 is selected by `.python-version`. `uv.lock` fixes package versions; only Jean changes shared dependencies. The application environment is independent of the machine hosting the model. Gradio is included for the UI; model weights and PyTorch are not installed by this project. Tests and fixture-based UI development do not require a GPU or model server.

For model access, copy `.env.example` to your ignored `.env` and configure your local or remote compatible server. See [portable setup](docs/SETUP.md). Actual inference requires a reachable model service with suitable computing resources; no particular cluster or GPU model is required by the client.

## File ownership

```text
bern-archives-apertus/
  core/                  Jean: configuration, data/search, model client and answer service
  scripts/               Jean: optional model-service utilities
  contracts.py           Jean integrates agreed UI/backend type changes
  ui/                    Dyane98: interface-only helpers
  app.py                 Dyane98 creates the UI entry point during S1
  fixtures/ui/           Shared, Jean-reviewed DEMO payloads, not model replies
  tests/core/            Jean: backend tests
  evaluation/            Jean: versioned evaluator-only reference snapshots
  tests/ui/              Dyane98: interface tests
  tests/test_contracts.py Jean: shared response checks
  docs/SETUP.md          Jean: runtime/setup instructions
  docs/USER_GUIDE.md     Dyane98: user instructions and demonstration
  pyproject.toml         Jean: dependencies/configuration
  uv.lock                Jean: generated dependency lock
  .env                   Local, ignored; never commit
  data/                  Raw/derived files ignored except this directory's README
  runs/                  Runtime logs/receipts ignored except its README
```

`app.py` now provides the evidence explorer with separate LIVE and DEMO modes. LIVE uses `core.service.answer_question` and requires a completed dataset plus the configured model connection; DEMO loads explicitly labelled fixtures without inference. Launch with `uv run --locked python app.py`; see [M1 instructions](docs/M1.md). The shared response shapes remain in `contracts.py`; live errors never fall back to fixtures.

Source search requires a successfully built dataset selected by `BERN_DATA_DIR`; it never fabricates a result when data is missing. `answer_question` retrieves evidence, calls the configured Apertus service and checks cited IDs/quotes before returning. The initial explicit/natural-language location checks succeeded; broader semantic quality and nonempty-evidence abstention remain unmeasured. See [dataset commands](docs/J2.md), [answer commands](docs/J3.md) and [evaluation instructions](docs/J4.md).

```bash
uv run --locked python -m core.answer_cli \
  "According to I.1, what is the place called?" \
  --transcription-id 16 --data-dir data/derived/j2-full \
  --out runs/j3-location-01
```

Use a new output directory for each attempt. The source dataset stays unchanged; run logs retain both failed and successful replies. No inference runs simply by importing the modules. Citation checks verify references and exact spans, not whether a claim logically follows from its quote.

## Avoid editing the same files

Use **separate clones/checkouts**, not two editors in the same folder. For the first task, start from clean main:

```bash
git switch main
git pull --ff-only
# Jean:
git switch -c jean/backend
# Dyane uses a separate clone and instead runs:
git switch -c jeni/ui
```

Each person runs only their own branch command. Do not rerun `switch -c` if the branch already exists; switch to it instead. Jean works in backend/configuration files, Dyane in UI/user-guide files. Commit only your assigned paths, not `git add .` over someone else's work. If the UI needs a contract/dependency change, agree it and let Jean make that change. Integrate early through a reviewed change; never resolve a conflict by discarding the other person's files.

`.github/CODEOWNERS` requests the appropriate reviewer when GitHub supports it. It is **not a file lock** and branch protection is not enabled by this scaffold.

## Data and model rights

Our original code is **MIT licensed**; see [LICENSE](LICENSE). MIT does not relicense Apertus weights, the Swiss Federal Archives/University of Bern edition, source excerpts, slides or literature. The Stapfer SQL resource is linked by [opendata.swiss](https://opendata.swiss/en/dataset/stapfer-enquete-schule-in-der-schweiz-1799), with its own [open-use terms](https://opendata.swiss/terms-of-use#terms_open). Preserve source references and the scholarly edition credit. The short original-text excerpt in the UI fixture retains that provenance; its English response is our authored display example, not a model result.

Do not commit raw SQL/datasets, internal notes, modern contributor contacts, meeting transcripts, credentials, model weights or run logs. The private repository setting is not a substitute for that rule. The public projection follows its documented allowlist; independent content/rights review and answer evaluation remain explicit work.
