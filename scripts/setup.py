"""Ask for local settings once, preserve private files, and start both Docker pages."""

import argparse
import getpass
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
from urllib.parse import urlparse

from dotenv import dotenv_values

from core.config import Settings
from scripts.configure_review import configure, validate_configuration

ROOT = Path(__file__).resolve().parents[1]


class SetupError(Exception):
    """An actionable message written by the installer, never arbitrary private input."""


def ask(label, default=""):
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip() or default
    if not value:
        raise SetupError(f"{label} is required")
    return value


def read_settings(path):
    if not path.exists():
        return None
    if not path.is_file() or path.is_symlink():
        raise SetupError(f"{path.name} must be a regular local file")
    return dict(dotenv_values(path, interpolate=False))


def write_settings(path, values):
    # Single quotes keep dollars, spaces and # literal in dotenv and Compose.
    lines = []
    for key, value in values.items():
        value = str(value)
        if any(c in value for c in "\r\n\x00"):
            raise SetupError("Settings must contain single-line values")
        escaped = value.replace("'", "\\'")
        lines.append(f"{key}='{escaped}'\n")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.writelines(lines)
    path.chmod(0o600)


def directory(root, value):
    path = Path(value).expanduser()
    return (root / path).resolve() if not path.is_absolute() else path.resolve()


def port(value):
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise SetupError("Web ports must be whole numbers") from error
    if not 1024 <= number <= 65535:
        raise SetupError("Use a web port between 1024 and 65535")
    return number


def prepare(root, args, *, native_linux):
    """Validate all inputs before writing. Never change an existing settings file."""
    auth = read_settings(root / ".env.review-oauth")
    model = read_settings(root / ".env")
    compose = read_settings(root / ".env.compose")
    if compose is None:
        data = directory(root, args.data_dir or ask("Completed J2 dataset folder", "data/derived/j2-full"))
        runs = directory(root, args.runs_dir or ask("Saved model runs folder", "runs"))
        originals = directory(root, args.original_reviews_dir or ask(
            "Original review exports folder (empty is allowed)", "runs/review-exports"))
        accounts = directory(root, args.account_reviews_dir or ask(
            "New account reviews folder", "runs/reviewer-exports"))
        live_port = port(args.live_port or ask("LIVE web port", "17860"))
        review_port = port(args.review_port or ask("Review web port", "17863"))
        default_url = (model or {}).get("BERN_APERTUS_BASE_URL") or "http://127.0.0.1:8010/v1"
        if not native_linux and urlparse(default_url).hostname in {"127.0.0.1", "localhost"}:
            default_url = default_url.replace(urlparse(default_url).hostname, "host.docker.internal", 1)
        model_url = args.model_url or ask("Model /v1 URL reachable from Docker", default_url)
        compose = {
            "COMPOSE_PROJECT_NAME": getattr(args, "project_name", None) or "bern-archives-ui",
            "BERN_DATA_HOST_DIR": data.as_posix(), "BERN_SAVED_RUNS_HOST_DIR": runs.as_posix(),
            "BERN_ORIGINAL_REVIEWS_HOST_DIR": originals.as_posix(),
            "BERN_ACCOUNT_REVIEWS_HOST_DIR": accounts.as_posix(),
            "BERN_LIVE_PORT": live_port, "BERN_REVIEW_PORT": review_port,
            "BERN_DOCKER_MODEL_URL": model_url,
            "BERN_CONTAINER_UID": os.getuid() if hasattr(os, "getuid") else 1000,
            "BERN_CONTAINER_GID": os.getgid() if hasattr(os, "getgid") else 1000,
            "BERN_SETUP_HOST_NETWORK": "1" if native_linux and urlparse(model_url).hostname in {
                "127.0.0.1", "localhost", "::1"} else "0",
        }
        compose["COMPOSE_FILE"] = ("compose.yaml:compose.host-network.yaml"
                                   if compose["BERN_SETUP_HOST_NETWORK"] == "1" else "compose.yaml")
    elif any(getattr(args, field) is not None for field in (
        "data_dir", "runs_dir", "original_reviews_dir", "account_reviews_dir", "live_port", "review_port", "model_url")):
        raise SetupError(".env.compose already exists; edit it locally instead of passing replacement settings")

    required = ("BERN_DATA_HOST_DIR", "BERN_SAVED_RUNS_HOST_DIR", "BERN_ORIGINAL_REVIEWS_HOST_DIR",
                "BERN_ACCOUNT_REVIEWS_HOST_DIR", "BERN_DOCKER_MODEL_URL")
    if any(not compose.get(key) for key in required):
        raise SetupError(".env.compose is incomplete; follow compose.env.example without replacing private settings")
    data, runs, originals, accounts = [directory(root, compose[key]) for key in required[:4]]
    if not all((data / name).is_file() for name in ("_SUCCESS.json", "search.sqlite3")):
        raise SetupError("The dataset folder needs _SUCCESS.json and search.sqlite3. Build or obtain J2 data first")
    if not runs.is_dir() or not any((p / "_COMPLETE.json").is_file()
                                  and (p / "run-manifest.json").is_file() for p in runs.iterdir() if p.is_dir()):
        raise SetupError("The saved runs folder needs at least one immediate completed model run, not just exports")
    # Writable exports must never land in a completed run or the dataset/original collection.
    for protected in [data, originals, *[p for p in runs.iterdir() if (p / "_COMPLETE.json").is_file()]]:
        if accounts == protected or accounts.is_relative_to(protected) or protected.is_relative_to(accounts):
            raise SetupError("New account exports must be separate from data, original reviews and completed runs")
    for protected in [data, *[p for p in runs.iterdir() if (p / "_COMPLETE.json").is_file()]]:
        if originals == protected or originals.is_relative_to(protected):
            raise SetupError("Original review exports must be outside data and completed run folders")
    live_port, review_port = port(compose.get("BERN_LIVE_PORT", "17860")), port(compose.get("BERN_REVIEW_PORT", "17863"))
    if live_port == review_port:
        raise SetupError("LIVE and review need different ports")
    Settings(base_url=compose["BERN_DOCKER_MODEL_URL"])
    host = compose.get("BERN_SETUP_HOST_NETWORK", "0") == "1"
    if native_linux and urlparse(compose["BERN_DOCKER_MODEL_URL"]).hostname in {"127.0.0.1", "localhost", "::1"}:
        host = True
    if host and not native_linux:
        raise SetupError("This host-network configuration requires native Linux; use a container-reachable model URL")

    callback = f"http://127.0.0.1:{review_port}/auth/huggingface/callback"
    if auth is None:
        client_id = args.client_id or ask("Hugging Face public OAuth client ID (not a token or secret)")
        validate_configuration(client_id, callback)
    else:
        client_id = auth.get("BERN_REVIEW_HF_CLIENT_ID", "")
        validate_configuration(client_id, auth.get("BERN_REVIEW_HF_REDIRECT_URI", ""))
        if auth["BERN_REVIEW_HF_REDIRECT_URI"] != callback:
            raise SetupError("Existing OAuth callback must match the review port and 127.0.0.1; edit it locally first")
        if len(auth.get("BERN_REVIEW_SESSION_SECRET") or "") < 32:
            raise SetupError("Existing OAuth session secret is missing or too short; repair that private file locally")
        if args.client_id and args.client_id != client_id:
            raise SetupError("Existing OAuth client ID is preserved; edit it locally to change it")
    if model is None:
        model = {"BERN_APERTUS_BASE_URL": compose["BERN_DOCKER_MODEL_URL"],
                 "BERN_APERTUS_MODEL": args.model_id or ask("Served model ID", "swiss-ai/Apertus-v1.5-8B"),
                 "BERN_APERTUS_TIMEOUT": "120", "BERN_APERTUS_API_KEY": getpass.getpass(
                     "Model API key (hidden; Enter if not required): ")}
    elif args.model_id and model.get("BERN_APERTUS_MODEL") != args.model_id:
        raise SetupError("Existing model ID is preserved; edit .env locally to change it")
    Settings(base_url=compose["BERN_DOCKER_MODEL_URL"], model=model.get("BERN_APERTUS_MODEL", ""),
             timeout=float(model.get("BERN_APERTUS_TIMEOUT", "120")))
    if not model.get("BERN_APERTUS_MODEL"):
        raise SetupError(".env needs BERN_APERTUS_MODEL")

    for path in (originals, accounts):
        if path.exists() and not path.is_dir():
            raise SetupError("An export folder is not a directory")
        path.mkdir(parents=True, exist_ok=True)
    if not os.access(accounts, os.W_OK):
        raise SetupError("The account export folder must be writable by the current user")
    if auth is None:
        configure(client_id, callback, root / ".env.review-oauth")
    for name, values in ((".env", model), (".env.compose", compose)):
        if not (root / name).exists():
            write_settings(root / name, values)
    print("Private configuration ready; existing files and review exports were preserved.")
    print(f"Register this exact Redirect URI in your HF OAuth application: {callback}")
    return compose, host


def docker(command, root, *, timeout=60):
    try:
        result = subprocess.run(["docker", *command], cwd=root, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SetupError("Docker is unavailable or timed out. Start Docker Desktop/Engine and retry") from error
    if result.returncode:
        # Docker diagnostics may include expanded environment; never echo them automatically.
        raise SetupError("Docker command failed. Check Docker and use the README's private troubleshooting commands")
    return result.stdout.strip()


def launch(root, compose, host, project):
    for key, default in (("BERN_LIVE_PORT", "17860"), ("BERN_REVIEW_PORT", "17863")):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port(compose.get(key, default))))
            except OSError as error:
                raise SetupError("A web port is already in use. Open the existing page or export work before stopping your own app") from error
    command = ["compose", "--project-name", project, "--env-file", ".env.compose", "-f", "compose.yaml"]
    if host:
        command += ["-f", "compose.host-network.yaml"]
    for identity in docker([*command, "ps", "-a", "-q"], root).split():
        details = json.loads(docker(["inspect", identity], root))[0]
        owner = details["Config"]["Labels"].get("com.docker.compose.project.working_dir", "")
        if not owner or Path(owner).resolve() != root.resolve():
            raise SetupError("This Docker project belongs to another checkout; choose a different --project-name")
    docker([*command, "config", "--quiet"], root)
    print("Building and starting the two web pages; the first download can take several minutes.", flush=True)
    docker([*command, "up", "--build", "-d", "--wait", "--wait-timeout", "180"], root, timeout=900)
    print(f"LIVE: http://127.0.0.1:{compose.get('BERN_LIVE_PORT', '17860')}/")
    print(f"Review: http://127.0.0.1:{compose.get('BERN_REVIEW_PORT', '17863')}/")
    print("Pages are ready. No model was started or answer generated; LIVE still needs a reachable model.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("client-id", "data-dir", "runs-dir", "original-reviews-dir", "account-reviews-dir",
                 "model-url", "model-id", "live-port", "review-port"):
        parser.add_argument("--" + flag)
    parser.add_argument("--project-name", help="Optional project name for a separate installation")
    parser.add_argument("--configure-only", action="store_true", help="Prepare settings without starting containers")
    args = parser.parse_args()
    try:
        if args.project_name and not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", args.project_name):
            raise SetupError("Use a lowercase Docker project name")
        docker(["compose", "version"], ROOT)
        operating_system = docker(["info", "--format", "{{.OperatingSystem}}"], ROOT)
        native_linux = sys.platform.startswith("linux") and "docker desktop" not in operating_system.lower()
        # Prevent shell overrides from silently changing paths, credentials, image or host bindings.
        if any(key.startswith("BERN_") or key.startswith("COMPOSE_") for key in os.environ):
            raise SetupError("Unset exported BERN_* and COMPOSE_* variables before setup; it uses the private files")
        compose, host = prepare(ROOT, args, native_linux=native_linux)
        project = args.project_name or compose.get("COMPOSE_PROJECT_NAME") or re.sub(r"[^a-z0-9_-]", "", ROOT.name.lower()).lstrip("-_")
        if not project:
            raise SetupError("Use --project-name with a lowercase Docker project name")
        if not args.configure_only:
            launch(ROOT, compose, host, project)
    except SetupError as error:
        print(f"Setup did not finish: {error}\nExisting private files were kept. No running service was stopped.", file=sys.stderr)
        return 1
    except (ValueError, OSError, EOFError, KeyboardInterrupt):
        # Do not print arbitrary input/exception strings, which could contain a pasted credential.
        print("Setup did not finish. Existing settings and running services were not stopped.\n"
              "Check the dataset/runs folders, Docker availability, unused web ports and matching OAuth callback.\n"
              "For a partly completed setup, keep the private files, fix them locally and run this command again.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
