"""Download a pinned Apertus checkpoint and prepare an optional, separate GPU server."""

import argparse
import json
from pathlib import Path
import shutil
import sys

from huggingface_hub import snapshot_download
from huggingface_hub.errors import GatedRepoError, HfHubHTTPError, LocalEntryNotFoundError

from scripts.setup import ROOT, SetupError, port, read_settings, write_settings

MODEL_ID = "swiss-ai/Apertus-v1.5-8B"
REVISION = "a411d838600baf0e3635a3daf66fb7c55fc97bb6"
IMAGE = "ghcr.io/swiss-ai/vllm_apertus_1.5_release@sha256:d85533f251c8272218ae2e519510836376e5a335b44f2204f193018e37753bc6"


def verify_snapshot(snapshot):
    """Check required files and indexed shards, not a fresh full weight hash audit."""
    snapshot = Path(snapshot).resolve(strict=True)
    if snapshot.name != REVISION:
        raise SetupError("The cached snapshot is not the pinned Apertus revision")
    required = ("config.json", "tokenizer.json", "tokenizer_config.json", "model.safetensors.index.json")
    if not all((snapshot / name).is_file() and (snapshot / name).stat().st_size > 0 for name in required):
        raise SetupError("The checkpoint is incomplete; rerun setup online to resume the download")
    index = json.loads((snapshot / "model.safetensors.index.json").read_text(encoding="utf-8"))
    mapping = index.get("weight_map", {})
    if not isinstance(mapping, dict) or not mapping or any(
        not isinstance(name, str) or Path(name).name != name or "\\" in name
        or not name.endswith(".safetensors") for name in mapping.values()):
        raise SetupError("Invalid checkpoint shard index")
    shards = set(mapping.values())
    if not all((snapshot / name).is_file() and (snapshot / name).stat().st_size > 0 for name in shards):
        raise SetupError("Checkpoint shards are missing; rerun setup online to resume the download")
    return snapshot


def acquire(cache, *, dry_run=False, offline=False, yes=False):
    cache = Path(cache).expanduser().resolve()
    if offline:
        return verify_snapshot(snapshot_download(repo_id=MODEL_ID, revision=REVISION,
                               cache_dir=cache, local_files_only=True))
    plan = snapshot_download(repo_id=MODEL_ID, revision=REVISION, cache_dir=cache, dry_run=True)
    if not plan or any(item.commit_hash != REVISION or item.file_size is None for item in plan):
        raise SetupError("The Hub did not return a complete, revision-bound download plan")
    needed = sum(item.file_size for item in plan if item.will_download)
    total = sum(item.file_size for item in plan)
    print(f"Pinned checkpoint: {MODEL_ID} @ {REVISION}")
    print(f"Checkpoint files: {total / 1024**3:.2f} GiB; remaining download: {needed / 1024**3:.2f} GiB")
    if dry_run:
        print("Dry run only: no model weights downloaded and no server configuration written.")
        return None
    ancestor = cache
    while not ancestor.exists():
        ancestor = ancestor.parent
    if needed and shutil.disk_usage(ancestor).free < needed + 4 * 1024**3:
        raise SetupError("Not enough free disk space for the remaining checkpoint plus a 4 GiB safety margin")
    if needed and not yes and input("Download these model files now? [y/N]: ").strip().lower() not in {"y", "yes"}:
        raise SetupError("Download cancelled; existing files were kept")
    # Reuses complete files and the Hub's partial-download recovery; never force-download or delete a cache.
    return verify_snapshot(snapshot_download(repo_id=MODEL_ID, revision=REVISION, cache_dir=cache, max_workers=4))


def configure_server(root, snapshot, *, server_port=8010, gpu="0", utilization=.9):
    server_port = port(server_port)
    if not str(gpu).isdigit() or not .1 <= utilization <= .95:
        raise SetupError("Select one numeric GPU index and a memory fraction between 0.1 and 0.95")
    values = {
        "COMPOSE_PROJECT_NAME": "bern-apertus-local",
        "BERN_APERTUS_SNAPSHOT": str(Path(snapshot).resolve()).replace("\\", "/"),
        "BERN_APERTUS_REVISION": REVISION, "BERN_APERTUS_PORT": str(server_port),
        "BERN_APERTUS_GPU": str(gpu), "BERN_APERTUS_GPU_MEMORY_UTILIZATION": str(utilization),
    }
    path = root / ".env.apertus"
    existing = read_settings(path)
    if existing is None:
        write_settings(path, values)
    elif any(existing.get(key) != value for key, value in values.items()):
        raise SetupError(".env.apertus already contains other settings and was kept unchanged; edit it locally")
    print("Checkpoint files checked; .env.apertus is ready. No GPU server has been started.")
    print("To start it explicitly on a supported NVIDIA Docker host:")
    print("docker compose --env-file .env.apertus -f compose.apertus.yaml up -d --wait --wait-timeout 600")
    print(f"Native endpoint: http://127.0.0.1:{server_port}/v1")
    print("Then run the separate web-page setup: uv run --locked python -m scripts.setup")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "model-cache/huggingface")
    parser.add_argument("--dry-run", action="store_true", help="Show Hub metadata/size without downloading weights")
    parser.add_argument("--offline", action="store_true", help="Reuse an already cached pinned snapshot without network access")
    parser.add_argument("--yes", action="store_true", help="Approve the model download without an interactive confirmation")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--gpu", default="0")
    parser.add_argument("--gpu-memory-utilization", type=float, default=.9)
    args = parser.parse_args()
    try:
        if args.offline and args.dry_run:
            raise SetupError("Choose either --offline or --dry-run")
        port(args.port)
        if not args.gpu.isdigit() or not .1 <= args.gpu_memory_utilization <= .95:
            raise SetupError("Select one numeric GPU index and a memory fraction between 0.1 and 0.95")
        cache = args.cache_dir.expanduser().resolve()
        if cache.is_relative_to(ROOT.resolve()) and not cache.is_relative_to((ROOT / "model-cache").resolve()):
            raise SetupError("Inside the repository use model-cache/, not data, runs or source folders")
        snapshot = acquire(args.cache_dir, dry_run=args.dry_run, offline=args.offline, yes=args.yes)
        if snapshot is not None:
            configure_server(ROOT, snapshot, server_port=args.port, gpu=args.gpu,
                             utilization=args.gpu_memory_utilization)
    except GatedRepoError:
        print("Apertus access is gated. Accept its conditions on Hugging Face, then run `uv run --locked hf auth login`.\n"
              "Use an account with model access; dashboard OAuth login alone does not authorize downloads.", file=sys.stderr)
        return 1
    except LocalEntryNotFoundError:
        print("The pinned model is not fully cached. Run this command online after obtaining Hugging Face access.", file=sys.stderr)
        return 1
    except SetupError as error:
        print(f"Apertus setup did not finish: {error}", file=sys.stderr)
        return 1
    except (HfHubHTTPError, OSError, ValueError, EOFError, KeyboardInterrupt):
        # Never echo provider URLs/headers or arbitrary exceptions that could contain credentials.
        print("Apertus setup did not finish. Check Hub login/access, network, disk space and checkpoint files.\n"
              "Existing files were kept. Retry the same command to reuse completed downloads.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
