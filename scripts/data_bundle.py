"""Install only manifest-bound Stapfer data; never trust tar paths or overwrite files."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile

BUNDLE_NAME = "dataset-challenge3.tar.gz"
MANIFEST_NAME = "dataset-challenge3.manifest.json"
RUN_NAMES = tuple(f"j4-bound-{model}-{split}-03" for model in ("apertus", "qwen")
                  for split in ("development", "evaluation"))
DATA_FILES = frozenset(("_SUCCESS.json", "search.sqlite3", "school_teachers.jsonl", "teachers.jsonl",
    "schema.json", "schools.jsonl", "transformations.jsonl", "answers.jsonl", "documents.jsonl",
    "places.jsonl", "public_policy.json", "questions.jsonl", "source_manifest.json",
    "validation_report.json", "answers.tsv"))
MAX_BYTES = 1024**3
MAX_FILES = 10000


class BundleError(ValueError):
    """Safe setup message, without private source content."""


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024**2), b""):
            value.update(block)
    return value.hexdigest()


def allowed_name(name):
    if not isinstance(name, str) or any(c in '\\:\x00<>"|?*' or ord(c) < 32 for c in name):
        return False
    path = PurePosixPath(name)
    if path.is_absolute() or str(path) != name or not path.parts:
        return False
    reserved = {"con", "prn", "aux", "nul", *[f"com{i}" for i in range(1,10)], *[f"lpt{i}" for i in range(1,10)]}
    if any(part in {".", ".."} or part.startswith(".") or part.endswith((".", " "))
           or part.split(".")[0].lower() in reserved for part in path.parts):
        return False
    if path.parts[:3] == ("data", "derived", "j2-full"):
        return len(path.parts) == 4 and path.name in DATA_FILES
    if len(path.parts) >= 3 and path.parts[0] == "runs" and path.parts[1] in RUN_NAMES:
        return (path.suffix in {".json", ".jsonl", ".md", ".py", ".toml", ".txt", ".lock", ".tsv"}
                or path.parts[2:] == ("references", "Read-PublicReferenceSource.ps1"))
    if len(path.parts) == 4 and path.parts[:2] == ("runs", "review-exports"):
        return (any(path.parts[2].startswith(run + "-") for run in RUN_NAMES)
                and re.fullmatch(r"[A-Za-z0-9_-]+", path.parts[2]) is not None
                and path.name in {"reviews.jsonl", "suggested-corrections.json", "amendment-provenance.json"})
    return False


def read_manifest(path):
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    files = manifest.get("files", {})
    if (manifest.get("format") != "stapfer-bootstrap-v1" or not isinstance(files, dict)
            or not 1 <= len(files) <= MAX_FILES or not re.fullmatch(r"[a-f0-9]{64}", manifest.get("archive_sha256", ""))):
        raise BundleError("Invalid dataset archive manifest")
    folded = set()
    for name, record in files.items():
        if (not allowed_name(name) or name.casefold() in folded or not isinstance(record, dict)
                or type(record.get("size")) is not int or record["size"] < 0
                or not re.fullmatch(r"[a-f0-9]{64}", record.get("sha256", ""))):
            raise BundleError("Unsafe, duplicate or malformed dataset manifest entry")
        folded.add(name.casefold())
    if sum(row["size"] for row in files.values()) > MAX_BYTES:
        raise BundleError("Dataset archive exceeds the supported unpacked size")
    return manifest


def verify_contents(root):
    """Use existing read-only dataset/run/review validators; no model calls or judgments."""
    from core.dataset_cli import verify
    from ui.review_records import import_session, load_run
    data = verify(root / "data/derived/j2-full")
    loaded = {name: load_run(root / "runs" / name, allow_evaluation=True) for name in RUN_NAMES}
    reviews = root / "runs/review-exports"
    if not reviews.is_dir() or not any(reviews.iterdir()):
        raise BundleError("Dataset archive omits the original saved review collection")
    for session in reviews.iterdir():
        run_name = next((name for name in RUN_NAMES if session.name.startswith(name + "-")), None)
        if run_name is None or not session.is_dir() or session.is_symlink():
            raise BundleError("Unexpected original review export")
        import_session(loaded[run_name], session.name, export_root=reviews)
    return {"dataset": data, "saved_runs": len(loaded), "review_exports": len(list(reviews.iterdir()))}


def destination(root, name):
    """Reject even a pre-existing parent symlink before any installation write."""
    path = root
    for part in PurePosixPath(name).parts:
        path = path / part
        if path.is_symlink():
            raise BundleError("A dataset destination is a symlink; preserve it and choose another checkout")
        if path != root.joinpath(*PurePosixPath(name).parts) and path.exists() and not path.is_dir():
            raise BundleError("A dataset parent path is not a directory; preserve it and choose another checkout")
    return path


def install_bundle(root, archive, manifest_path=None):
    root, archive = Path(root).resolve(), Path(archive).resolve()
    manifest_path = Path(manifest_path) if manifest_path else archive.with_name(MANIFEST_NAME)
    manifest = read_manifest(manifest_path)
    if digest(archive) != manifest["archive_sha256"]:
        raise BundleError("Dataset archive checksum differs from its manifest; obtain the intact bundle")
    files = manifest["files"]
    root.mkdir(parents=True, exist_ok=True)
    missing_bytes = sum(row["size"] for name, row in files.items() if not destination(root, name).exists())
    if shutil.disk_usage(root).free < sum(row["size"] for row in files.values()) + missing_bytes + 64 * 1024**2:
        raise BundleError("Not enough free disk space for staged verification and installation; free space and retry")
    with tempfile.TemporaryDirectory(prefix=".bern-data-", dir=root) as temporary:
        staging = Path(temporary)
        seen = set()
        with tarfile.open(archive, "r:*") as source:
            for member in source:
                name = member.name
                if (not member.isfile() or getattr(member, "sparse", None) is not None or name not in files
                        or name in seen or not allowed_name(name) or member.size != files[name]["size"]):
                    raise BundleError("Unsafe, duplicate, unexpected or incorrectly sized archive member")
                seen.add(name)
                target = staging.joinpath(*PurePosixPath(name).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as incoming, target.open("xb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing, length=1024**2)
                target.chmod(0o600)
                if digest(target) != files[name]["sha256"]:
                    raise BundleError("An unpacked dataset file failed its checksum")
        if seen != set(files):
            raise BundleError("Dataset archive is missing manifest entries")
        validation = verify_contents(staging)
        # Check every collision before adding any file; current data/reviews are never replaced.
        for name, record in files.items():
            target = destination(root, name)
            if target.exists() and (not target.is_file() or digest(target) != record["sha256"]):
                raise BundleError("Existing dataset or saved-run files differ; nothing was overwritten. Use another checkout")
        installed = 0
        for name, record in files.items():
            target = destination(root, name)
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation prevents replacing a file that appeared after collision checks.
            with target.open("xb") as outgoing, staging.joinpath(*PurePosixPath(name).parts).open("rb") as incoming:
                shutil.copyfileobj(incoming, outgoing, length=1024**2)
            target.chmod(0o600)
            if digest(target) != record["sha256"]:
                raise BundleError("A copied file failed verification; keep the archive and inspect disk health")
            installed += 1
    print(f"Dataset bundle verified: {installed} files installed; {len(files) - installed} identical files reused.")
    return {"installed": installed, "reused": len(files) - installed, "validation": validation}
