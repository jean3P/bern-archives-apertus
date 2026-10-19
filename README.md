# Stapfer evidence explorer

An Apertus-powered explorer of the **1799 Stapfer school survey**, built for the University of Bern's **Deciphering Archives with Apertus** challenge. It preserves the edited archival text and lets readers inspect the evidence behind an answer.

The application has two independent pages:

| Page | Local address used in this guide | Purpose |
| --- | --- | --- |
| LIVE evidence explorer | http://127.0.0.1:17860/ | Ask a fresh question, retrieve archival evidence and generate a cited Apertus answer |
| Saved run review | http://127.0.0.1:17863/ | Inspect recorded Apertus/Qwen answers and create separate human reviews with Hugging Face sign-in |

**Opening the review page never runs a model. Clicking Ask in LIVE does.** A valid citation is not proof of a correct interpretation. DEMO mode shows labelled fixtures, not model results.

You can run both pages with Python, or start both with Docker Compose after the one-time configuration below. Neither method installs or starts a model server automatically.

## New installation with one setup command

Install Git, [uv](https://docs.astral.sh/uv/getting-started/installation/) and Docker Desktop/Engine with Compose 2.24.4 or newer, and start Docker. Obtain access to this private repository, a completed J2 dataset, saved model-run folders and a reachable Apertus endpoint. Register a public Hugging Face OAuth application without a client secret; keep its public client ID ready. You do not need another user's session secret or a GPU on the computer running these pages.

**No Apertus checkpoint or endpoint yet?** Follow [Download Apertus and optionally serve it locally](#download-apertus-and-optionally-serve-it-locally) first. A remote model endpoint is equally valid; saved-run review needs no model at all.

```bash
git clone https://github.com/jean3P/bern-archives-apertus.git
cd bern-archives-apertus
uv run --locked python -m scripts.setup
```

**The last line is the setup-and-launch command.** It asks for dataset/run locations, export folders, web ports, the model endpoint/ID and the public OAuth client ID. A model API key, if required, is entered without displaying it. Press Enter to accept a suggested value.

The command generates this installation's random session secret, creates ignored `.env`, `.env.review-oauth` and `.env.compose` with private permissions on Unix, prepares export folders, builds the Docker image and waits for both pages. The generated Compose settings also record the project name and network files, so the manual Compose commands below target this installation. On Windows, also restrict private-file access through your operating system. Inputs are mounted read-only and new account exports remain separate. No dataset, model weights or benchmark is downloaded, rebuilt or run.

When prompted about OAuth, register the exact callback shown by setup under **Redirect URIs** in your HF application. With the default ports it is:

```text
http://127.0.0.1:17863/auth/huggingface/callback
```

After startup open LIVE at **http://127.0.0.1:17860/** and review at **http://127.0.0.1:17863/** (or the ports you selected). The command automatically chooses the existing host-network override for a native Linux loopback-only model; Docker Desktop uses `host.docker.internal` for a suggested host-local endpoint. Page readiness does not establish model connectivity: test that separately with `core.health` as described below.

Existing configuration is reused, never overwritten or given a new secret. Run the same setup command after editing your own private settings to restart stopped containers. If a page is already running, open it instead: setup reports the occupied port and stops without killing anything. Export in-memory reviews before stopping your own old native/Docker app. Unset exported `BERN_*`/`COMPOSE_*` variables before using setup so they cannot silently override its private files.

If setup reports an error, keep the generated files, correct the indicated setting locally and retry. A failed Docker startup may leave this project's containers running; use the matching `down` command below only after exporting work. Advanced/manual configuration and separate native launch remain available in the following sections. `--configure-only` prepares settings without launching Docker; `--help` lists optional arguments for scripted installation.

## Download Apertus and optionally serve it locally

Skip this section if you already have a compatible remote Apertus endpoint. The web-page setup does not silently download large models or claim a GPU.

1. Open the [official Apertus model page](https://huggingface.co/swiss-ai/Apertus-v1.5-8B), read and accept its access conditions with your own HF account. Then authenticate the download tool locally:

   ```bash
   uv run --locked hf auth login
   ```

   **This is different from the review dashboard's OAuth sign-in.** Use an account authorized to download the model. Never put an HF token in Git, the OAuth client-ID field, the Docker image or a command pasted into chat.

2. Download or reuse the pinned checkpoint:

   ```bash
   uv run --locked python -m scripts.setup_apertus
   ```

   The helper shows the checkpoint size and remaining download before asking permission. It reuses complete cached files, supports interrupted-download recovery and checks required configuration/tokenizer files plus indexed weight shards. It writes separate ignored `.env.apertus` settings without overwriting existing settings. It **does not start Docker, load the model or change the web apps**.

   The default ignored cache is `model-cache/huggingface/`. Use `--cache-dir /your/model/cache` for another disk or an existing Hugging Face **hub cache** (the folder containing `models--swiss-ai--Apertus-v1.5-8B`, not a single checkpoint file). `--dry-run` checks online metadata and size without downloading weights or writing server settings; `--offline` reuses an already complete pinned snapshot without contacting the Hub. `--yes` approves an intentional scripted download.

   Leave ample disk space for both weights and the Docker image: the helper checks remaining weight bytes plus a 4 GiB margin, but that is not the image's storage budget. Cached-file checks are not a new full cryptographic weight audit. [HF documents snapshot reuse and download planning](https://huggingface.co/docs/huggingface_hub/guides/download).

3. **Only if serving locally**, use an NVIDIA GPU host with Docker GPU access and BF16 support. This pinned server image targets Linux amd64; native Linux or an appropriately configured Windows/WSL2 Docker GPU environment is needed. Mac/CPU-only computers should use a remote endpoint. Install/configure GPU support yourself using [NVIDIA's Container Toolkit guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html); the helper does not alter drivers or restart Docker.

   Inspect `.env.apertus` before starting. Defaults select GPU `0`, port `8010`, an 8,192-token context, BF16 and a **90% GPU memory allocation**. This is intended for an otherwise available GPU, not a promise that it fits every GPU. Weights, activations and KV cache all need memory; use a sufficiently large GPU and check free VRAM. Adjust the GPU/memory fraction locally when sharing hardware. No other job will be stopped to make space. This local deployment has not been qualified on every consumer GPU.

   ```bash
   docker compose --env-file .env.apertus -f compose.apertus.yaml config --quiet
   docker compose --env-file .env.apertus -f compose.apertus.yaml up -d --wait --wait-timeout 600
   ```

   Docker pulls the pinned Swiss AI vLLM image if missing. It mounts the downloaded snapshot read-only, serves the public model ID `swiss-ai/Apertus-v1.5-8B` on `http://127.0.0.1:8010/v1`, and checks readiness without generating an answer. The server runs offline with no HF token passed into its container. The image/model pins are in `scripts/setup_apertus.py` and `compose.apertus.yaml`; do not replace them with `latest` to reproduce this setup. Apertus 1.5 uses the [publisher's adapted vLLM image](https://huggingface.co/swiss-ai/Apertus-v1.5-8B#vllm), not an assumed compatible generic image.

4. Run `uv run --locked python -m scripts.setup` for the two web pages. Accept the suggested host-local model URL, or enter the reachable remote URL. On native Linux the UI helper handles the host-loopback networking override; Docker Desktop uses `host.docker.internal`. Native Python clients use `http://127.0.0.1:8010/v1` in `.env` instead. The helper never rewrites an existing `.env`; keep native and Docker endpoint choices appropriate to their environments.

The optional GPU server is a **separate Compose project** from the two CPU web pages. Stop only this local model project when you no longer need it:

```bash
docker compose --env-file .env.apertus -f compose.apertus.yaml down
```

This preserves the host checkpoint cache and does not stop the UI project. Check that the model is idle before stopping it. If port 8010 is already used, reuse that existing endpoint or edit your own model/UI ports; do not stop an unrelated server. Unset stale exported `BERN_*`/`COMPOSE_*` overrides when using the generated files. Logs and configuration can contain private information: use `config --quiet`, and do not publish private settings. No benchmark is run by these setup commands.

## Already configured run now

If you already have your local settings and saved data—as in the existing reviewer installation—save your work and update from the repository folder:

```bash
git switch main
git pull --ff-only
uv sync --locked --group review-auth
```

**To review saved answers immediately:**

```bash
uv run --locked --group review-auth python review_app.py --runs-root runs --allow-evaluation --port 17863
```

Open **http://127.0.0.1:17863/**. Keep your existing `--runs-root` path if your saved runs are elsewhere. Sign in with your own HF account and choose **Start / resume my Hugging Face review**. Your private `.env.review-oauth` stays unchanged by a Git pull.

**For LIVE, in another terminal:**

```bash
uv run --locked python app.py --port 17860
```

Open **http://127.0.0.1:17860/**. This needs the completed dataset and a reachable model endpoint in `.env`.

**Or use Docker instead**, after preparing `.env.compose` and the files below:

```bash
docker compose --env-file .env.compose up --build -d
```

Do not start Docker and native copies on the same ports. Export in-memory reviews before stopping an old app. If this is a new installation, complete the numbered setup sections before running these commands.

## What you need

- Access to this private repository.
- uv for the configuration steps and native execution; Docker Engine/Desktop with Compose if using containers. Use Linux containers in Docker Desktop.
- A completed public dataset for LIVE. Build it from the supplied SQL ZIP, or obtain the existing verified J2 output.
- A reachable OpenAI-compatible Apertus endpoint for fresh answers. The UI itself does not need a GPU.
- Saved model-run folders for review. Original review exports are a separate collection.
- A Hugging Face OAuth application for reviewer sign-in. Each installation generates its own private session secret.

**Git contains code, not your datasets, saved answers, review exports, model weights or private configuration.** Pulling main alone cannot populate the review page or enable OAuth.

## 1 Get the code

```bash
git clone https://github.com/jean3P/bern-archives-apertus.git
cd bern-archives-apertus
uv sync --locked --group review-auth
```

For an existing checkout, save your own work, then use `git switch main` and `git pull --ff-only`. Keep each person's work in a separate checkout/branch.

The native environment uses Python 3.11.16 and the committed `uv.lock`. The optional `review-auth` group supplies real self-hosted OAuth; it is not a Hugging Face Space mock login.

## 2 Prepare the archival dataset and LIVE settings

Place the supplied archive at `data/raw/stapferappdb_final.sql.zip`. To build a new output directory:

```bash
uv run --locked python -m core.dataset_cli build --source data/raw/stapferappdb_final.sql.zip --out data/derived/j2-full
uv run --locked python -m core.dataset_cli verify --data-dir data/derived/j2-full
```

If you already have a completed output, verify it instead of rebuilding or overwriting it. Details and the public-field policy are in [J2 data commands](docs/J2.md).

Copy `.env.example` to an ignored file named `.env`, using your file manager or shell. Set the endpoint, model ID and completed dataset directory:

```dotenv
BERN_APERTUS_BASE_URL=http://127.0.0.1:8010/v1
BERN_APERTUS_MODEL=swiss-ai/Apertus-v1.5-8B
BERN_APERTUS_TIMEOUT=120
BERN_APERTUS_API_KEY=
BERN_DATA_DIR=data/derived/j2-full
```

The address is an example: use your own local endpoint, private connection or HTTPS service. Keep keys out of Git. Check availability without generating an answer:

```bash
uv run --locked python -m core.health
```

The service must expose `/v1/models` and `/v1/chat/completions` and serve the configured model ID. LIVE uses the existing `apertus-qualified` / `bound` answering method; it does not replay benchmark answers. See [portable model setup](docs/SETUP.md).

## 3 Configure reviewer sign-in

In [Hugging Face application settings](https://huggingface.co/settings/applications), create/select a **public OAuth application without a client secret**. Request only account identity/profile access. In its **Redirect URIs** field—not just the homepage—register:

```text
http://127.0.0.1:17863/auth/huggingface/callback
```

The callback must return to this installation. Use `127.0.0.1` consistently rather than switching to `localhost`, and keep the path exact. [Hugging Face explains callback matching and public clients](https://huggingface.co/docs/hub/oauth).

Run once, replacing `YOUR_PUBLIC_CLIENT_ID` with the registered client ID:

```bash
uv run --locked python -m scripts.configure_review --client-id YOUR_PUBLIC_CLIENT_ID
```

This creates ignored `.env.review-oauth`, generates a random session secret locally without displaying it, and refuses to overwrite an existing configuration. It contains:

```dotenv
BERN_REVIEW_HF_CLIENT_ID=your_registered_public_client_id
BERN_REVIEW_HF_REDIRECT_URI=http://127.0.0.1:17863/auth/huggingface/callback
BERN_REVIEW_SESSION_SECRET=generated_locally_do_not_share
```

Edit that private file if changing the callback. On Unix it is created with owner-only permissions; on Windows also restrict access through the operating system. Never copy another installation's session secret into chat or Git. Restart the review process after editing its configuration, first exporting any in-memory reviews.

## 4 Supply saved runs and review folders

Obtain the existing saved runs separately. The expected layout is:

```text
runs/
  j4-bound-apertus-development-03/   # completed recorded run, including _COMPLETE.json
  j4-bound-apertus-evaluation-03/
  j4-bound-qwen-development-03/
  j4-bound-qwen-evaluation-03/
  review-exports/                   # original Jean/Jeni exports, read-only in the UI
  reviewer-exports/                 # new account-specific exports, writable and persistent
```

Use another parent directory with `--runs-root` if necessary. Original exports belong in this checkout's `runs/review-exports/` for native execution. Preserve complete exports, suggestions and saved-run seals; do not edit model answers or reference snapshots.

Create the export directories if absent; existing files are not changed:

```bash
uv run --locked python -c "from pathlib import Path; [Path(p).mkdir(parents=True,exist_ok=True) for p in ('runs/review-exports','runs/reviewer-exports')]"
```

## Run natively

Use two terminals in the repository folder.

**LIVE explorer:**

```bash
uv run --locked python app.py --port 17860
```

**Review dashboard:**

```bash
uv run --locked --group review-auth python review_app.py --runs-root runs --allow-evaluation --port 17863
```

Open the addresses in the first table on the computer running these processes. No SSH is needed when the server and browser are on your personal computer. For a remote installation, arrange your own private connection; a localhost link is not a public address.

Both native commands bind to loopback by default. The explicit ports avoid confusing a review process on one port with a callback pointing at another.

## Run both pages with Docker Compose

For the guided configuration and launch, use `uv run --locked python -m scripts.setup` above. The remaining instructions are the manual alternative. Docker launches the web clients, not a GPU model server, data download, importer or benchmark.

1. Copy `compose.env.example` to ignored `.env.compose`.
2. Edit its host directories to point at your completed dataset, saved runs, original review exports and writable account exports. All four directories must already exist. Docker deliberately refuses to create a missing input directory silently.
3. Set `BERN_DOCKER_MODEL_URL` to an endpoint reachable **from inside a container**. For a host service under Docker Desktop, use `http://host.docker.internal:8010/v1`; for a remote model, use its reachable URL.
4. On native Linux, set `BERN_CONTAINER_UID` and `BERN_CONTAINER_GID` to your directory owner's IDs (`id -u` / `id -g`). Docker Desktop users normally keep the defaults. The account-export directory must be writable by this user; do not make private data world-writable.

Validate without printing secret-bearing resolved configuration, then start both pages:

```bash
docker compose --env-file .env.compose config --quiet
docker compose --env-file .env.compose up --build -d
docker compose --env-file .env.compose ps
```

Use the same browser addresses as native execution. Do not run native and Docker copies on the same host ports simultaneously. If changing the review port, update both the callback in `.env.review-oauth` and the registered HF application settings.

The containers run without GPU access and expose ports only on host loopback. The image excludes credentials, datasets, runs, Git history and model files. Data, recorded runs and originals are mounted read-only; new account reviews persist in the separate writable host directory. Container removal does not delete that directory.

Check model connectivity without inference:

```bash
docker compose --env-file .env.compose exec live python -m core.health
```

### Native Linux and a loopback-only model

Container `127.0.0.1` normally means the container itself, not the host. If a model or private tunnel listens only on the native Linux host's loopback, set `BERN_DOCKER_MODEL_URL=http://127.0.0.1:8010/v1` in `.env.compose` and use the optional host-network override (Compose 2.24.4+):

```bash
docker compose --env-file .env.compose -f compose.yaml -f compose.host-network.yaml up --build -d
```

This puts only LIVE on the Linux host network and keeps its web binding on `127.0.0.1`. Review retains ordinary bridge networking. Use the same `-f` options for `ps`, `logs`, `exec` and `down`. Do not expose the model publicly merely to make networking work.

### Stop or inspect the UI containers

```bash
docker compose --env-file .env.compose logs --tail 50 live review
docker compose --env-file .env.compose down
```

These commands operate on this Compose project, not an independently managed model server. Do not paste logs containing private archival content. Export in-memory reviews before stopping; exported host files persist.

## Use the pages

In **LIVE**, choose Development/Evaluation for a searchable example or enter a custom question. The selector loads only question text and transcription scope, not expected answers or human suggestions. Click **Ask**, read the answer, then inspect its original evidence and citation. **Answer produced — not human-reviewed** is a response status, not a correctness grade. An abstention does not prove the archive lacks the requested information.

In **Saved run review**, sign in, confirm your HF username, choose a run and select **Start / resume my Hugging Face review**. A new account starts Pending. Save each decision, then **Export my reviews separately** before closing or changing runs. Reload/resume to check persistence. Existing Jean/Jeni originals remain read-only; new account exports never replace them. See [review testing instructions](docs/REVIEW_SIGN_IN.md).

Signed-in users can compare with original judgments after exporting decisions for all cases in that run. Anonymous visitors can already read originals, so this is not a certified blind-review protocol. Historical manual reviews are not retroactively HF-authenticated. Account identity does not verify institutional affiliation or historical accuracy.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| HF button disabled | `.env.review-oauth` or equivalent environment is missing its client ID; a Git pull does not supply private settings |
| HF says Invalid redirect_uri | Register the exact callback under Redirect URIs for the client ID in use; check host/path and restart after local configuration changes |
| Sign-in returns to the wrong page | Ensure the callback port reaches this review process, not another app or old tunnel |
| No saved runs | `--runs-root` must contain immediate completed run folders, not just review exports |
| Original judgments missing | Supply exports in `runs/review-exports/` or the Docker original-export mount |
| LIVE reports an error | Verify the J2 dataset and run the model health command in the same native/container environment |
| Port already in use | Export work and stop your own old UI, or select another port and matching callback; do not stop unrelated services |
| Docker mount/permission error | Check existing source directories and the account-export UID/GID; inputs stay read-only |

## Measured results and limits

The full public import contains 2,250 transcription records, 92,524 answer rows and 60 questionnaire fields, with 92,336 nonblank answers indexed. These are different units, not 92,524 documents.

The reviewed, exposed 50-question benchmark has these recorded results:

| Candidate | Development | Evaluation | Total |
| --- | ---: | ---: | ---: |
| Apertus 8B pipeline | 17/20 | 21/30 | 38/50 |
| Qwen 32B comparator | 18/20 | 29/30 | 47/50 |

These are assisted human-review outcomes, not independent held-out gold or a claim that parameter count alone caused the difference. Apertus's original 40/50 review remains preserved; two later user-authorized amendments give 38/50. Valid quotes can accompany wrong, incomplete or misleading answers. The separate 100-document audit remains pending; question accuracy does not establish the organizer's processed-document target or an inexpensive-hardware result. See [evaluation protocol](docs/J4.md).

Our code is **MIT licensed**. This does not relicense model weights, the scholarly Stapfer edition, source excerpts or supplied material. Preserve original IDs, editorial markup, historical units and archival references. The dataset is linked by [opendata.swiss](https://opendata.swiss/en/dataset/stapfer-enquete-schule-in-der-schweiz-1799), with separate [open-use terms](https://opendata.swiss/terms-of-use#terms_open). Never commit credentials, raw/derived data, internal contributor details or private review exports.
