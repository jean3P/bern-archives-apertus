# Portable setup

The Python application and model server are separate. Develop on a machine supported by Python and uv; connect to a compatible Apertus server locally or remotely when you need inference. A particular cluster, GPU, Docker installation or model cache is not required for the client, software tests or fixture-based UI development.

## Install the application environment

```bash
git clone https://github.com/jean3P/bern-archives-apertus.git
cd bern-archives-apertus
uv sync --locked
uv run pytest -q
```

Authenticate to the private repository before cloning. Python 3.11.16 is selected automatically by uv. The committed lockfile fixes the application dependencies; it does not install model weights or certify a particular hardware deployment.

## Configure model access

Copy `.env.example` to `.env` using your file manager, `cp .env.example .env` on Linux/macOS, or `Copy-Item .env.example .env` in PowerShell. Set these values for your own server:

```dotenv
BERN_APERTUS_BASE_URL=http://127.0.0.1:8010/v1
BERN_APERTUS_MODEL=swiss-ai/Apertus-v1.5-8B
BERN_APERTUS_TIMEOUT=120
BERN_APERTUS_API_KEY=
```

The URL above is only a local example, not a required host or port. A remote compatible endpoint can use HTTPS, for example `https://your-model-server.example/v1`. Use HTTPS when sending credentials over a network. Leave the API key empty for a server that does not require authentication. Keep secrets and deployment-specific settings in ignored `.env`, never in the README or Git.

The client expects `/v1/models` and `/v1/chat/completions`, and verifies that the configured model ID is served. Check availability without generating a reply:

```bash
uv run python -m core.health
```

For one intentional connection-generation test, choose a new output path:

```bash
uv run python -m core.health --generate --out runs/connection-smoke.json
```

Previous receipts are not overwritten. This is a small connection prompt, not an archival question-answering evaluation.

Model deployment is managed separately by its operator. The optional service utility in `scripts/` is not part of portable application installation and needs operator-specific configuration. Private infrastructure commands are kept outside the repository documentation.

## Continue development

Follow [J2 commands](J2.md) to build and verify a completed dataset before source search. The J3 cited-answer service and [M1 live evidence explorer](M1.md) are now connected: run `uv run --locked python app.py` and use LIVE for actual retrieval/model answers, or explicitly choose DEMO for fixture-only interface work. Keep the model endpoint private and reachable. J4 evaluation is a separate intentional command; starting the UI does not run a benchmark or establish general answer accuracy.
