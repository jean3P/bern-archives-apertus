# Bern Archives with Apertus

An evidence-preserving pipeline and small search/answer demonstrator for the University of Bern's **Deciphering Archives with Apertus** challenge, using the edited Stapfer school-survey data.

## Status

This is the **J1 infrastructure scaffold**: uv project, shared response types, explicit demo fixtures, a private Apertus health client, owned H100 service helpers and software tests. The public-data importer, real archival search/answer service and UI remain J2/J3/S1 work. The service stubs intentionally raise instead of returning a fabricated result. No archival accuracy, 80% processing result or inexpensive-hardware benchmark is claimed.

## Quick start

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and authenticate to the private repository. Dyane98 must accept the collaborator invitation first.

```bash
git clone https://github.com/jean3P/bern-archives-apertus.git
cd bern-archives-apertus
uv sync --locked
uv run pytest -q
```

Python 3.11.16 is selected by `.python-version`. `uv.lock` fixes package versions; only Jean changes shared dependencies. Gradio is included for the UI, but neither PyTorch nor model weights are installed into this project environment. The GPU model runs in its existing pinned container separately.

## File ownership

```text
bern-archives-apertus/
  core/                  Jean: configuration, model client, future data/search/service
  scripts/               Jean: private H100 service/start/stop helpers
  contracts.py           Jean integrates agreed UI/backend type changes
  ui/                    Dyane98: interface-only helpers
  app.py                 Dyane98 creates the UI entry point during S1
  fixtures/ui/           Shared, Jean-reviewed DEMO payloads, not model replies
  tests/core/            Jean: backend tests
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

`app.py` is an assigned future file, not a working application already present in this scaffold. The agreed callable boundary is `core.service.search_records` and `core.service.answer_question`, returning the shapes in `contracts.py`. UI examples are always marked `mode: demo`; live mode requires real backend data and model replies.

## Avoid editing the same files

Use **separate clones/checkouts**, not two editors in the same folder. For the first task, start from clean main:

```bash
git switch main
git pull --ff-only
# Jean:
git switch -c jean/backend
# Dyane uses a separate clone and instead runs:
git switch -c sister/ui
```

Each person runs only their own branch command. Do not rerun `switch -c` if the branch already exists; switch to it instead. Jean works in backend/configuration files, Dyane in UI/user-guide files. Commit only your assigned paths, not `git add .` over someone else's work. If the UI needs a contract/dependency change, agree it and let Jean make that change. Integrate early through a reviewed change; never resolve a conflict by discarding the other person's files.

`.github/CODEOWNERS` requests the appropriate reviewer when GitHub supports it. It is **not a file lock** and branch protection is not enabled by this scaffold.

## H100 connection

See [setup commands](docs/SETUP.md). The Bern service binds only to `127.0.0.1:8010`; Track 2A's port 8000 is not used. The pinned existing model cache is mounted read-only, no weights are redownloaded, and no unrelated job/container is stopped. An optional private SSH tunnel lets another machine reach it; do not create a public share link.

## Data and model rights

Our original code is **MIT licensed**; see [LICENSE](LICENSE). MIT does not relicense Apertus weights, the Swiss Federal Archives/University of Bern edition, source excerpts, slides or literature. The Stapfer SQL resource is linked by [opendata.swiss](https://opendata.swiss/en/dataset/stapfer-enquete-schule-in-der-schweiz-1799), with its own [open-use terms](https://opendata.swiss/terms-of-use#terms_open). Preserve source references and the scholarly edition credit. The short original-text excerpt in the UI fixture retains that provenance; its English response is our authored display example, not a model result.

Do not commit raw SQL/datasets, internal notes, modern contributor contacts, meeting transcripts, credentials, model weights or run logs. The private repository setting is not a substitute for that rule. The public projection and its evaluation are later work.
