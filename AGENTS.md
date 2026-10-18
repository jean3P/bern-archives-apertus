# Bern repository working rules

Build the smallest complete archival-data/search/Apertus/evidence-viewer baseline before optimizing. J1 establishes infrastructure, not a finished archive application. Do not claim that display fixtures are model outputs or that the scholarly transcription has been corrected.

## File ownership

- Jean (`jean3P`): `core/`, `scripts/`, `tests/core/`, `contracts.py`, `tests/test_contracts.py`, `pyproject.toml`, `uv.lock`, `.env.example`, `.python-version`, `.github/`, data policy and `docs/SETUP.md`.
- Sister (`Dyane98`): `ui/`, `app.py` when added, `tests/ui/` and `docs/USER_GUIDE.md`.
- Jean integrates shared contracts/configuration and top-level README changes after discussion. Do not edit another owner's file while they work in it.
- Work in separate clones and branches (`jean/backend`, `sister/ui`). Never share one active checkout. CODEOWNERS requests reviewers; it is not a file lock or a guarantee of conflict-free merges.

## Boundaries

Use uv and the committed lockfile. Keep a single Python app and SQLite, not microservices. Keep original data/IDs/unknowns intact. Exclude internal comments and modern contributor contacts from public exports. Never commit `.env`, raw datasets, source transcripts, model weights or run logs. The MIT licence covers our code, not third-party data/models.

Only Jean manages the H100 service. It binds to loopback port 8010 and mounts the existing model cache read-only. Do not touch Track 2A, its port 8000, other containers, jobs, environments or global GPU/system configuration. Stop only this repository's recorded owned container, and only when idle.

The two public service function signatures in `core/service.py` are agreed scaffolding. They deliberately raise until J2/J3 implement real data/search/generation; never replace failure with a hardcoded answer. `fixtures/ui/*.demo.json` are interface-only authored examples, excluded from evaluation and data exports.
