"""Create the explicitly requested private bootstrap archive from allowlisted, validated inputs."""

import argparse
import gzip
import json
from pathlib import Path
import re
import sqlite3
import tarfile
from contextlib import closing

from scripts.data_bundle import (BUNDLE_NAME, DATA_FILES, MANIFEST_NAME, RUN_NAMES, BundleError,
                                 allowed_name, digest)


TOKEN = re.compile(rb"\b(?:hf_[A-Za-z0-9]{24,}|gh[pousr]_[A-Za-z0-9]{24,}|github_pat_[A-Za-z0-9_]{24,}|sk-[A-Za-z0-9_-]{24,})\b")
PRIVATE_KEYS = {"authorization", "api_key", "hf_token", "access_token", "refresh_token", "id_token",
                "client_secret", "session_secret", "password", "cookie"}


def scan_secrets(path):
    def walk(value, *, root=False):
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower() in PRIVATE_KEYS and item not in (None, "", False, [], {}):
                    # This historical audit field records a human's permission, not an HTTP credential.
                    audit_note = (root and path.name == "amendment-provenance.json" and key == "authorization"
                                  and isinstance(item, str) and len(item.split()) >= 6
                                  and ("user" in item.lower() or "jean" in item.lower())
                                  and ("authoriz" in item.lower() or "then do it" in item.lower())
                                  and not item.lower().startswith(("bearer ", "basic ", "token ")))
                    if not audit_note:
                        raise BundleError("Potential private credential field found; do not publish this input")
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    with path.open("rb") as source:
        tail = b""
        for block in iter(lambda: source.read(1024**2), b""):
            if TOKEN.search(tail + block):
                raise BundleError("Potential credential token found; do not publish this input")
            tail = block[-256:]
    if path.suffix == ".json":
        walk(json.loads(path.read_text(encoding="utf-8")), root=True)
    elif path.suffix == ".jsonl":
        with path.open(encoding="utf-8") as source:
            for line in source:
                if line.strip():
                    walk(json.loads(line))


def package(data, runs, reviews, output):
    data, runs, reviews, output = map(lambda p: Path(p).resolve(), (data, runs, reviews, output))
    output.mkdir(parents=True, exist_ok=True)
    archive, manifest_path = output / BUNDLE_NAME, output / MANIFEST_NAME
    if archive.exists() or manifest_path.exists():
        raise FileExistsError("The archive/manifest already exists; never overwrite a published bundle")
    sources = {"data/derived/j2-full/" + name: data / name for name in DATA_FILES}
    for name in RUN_NAMES:
        for path in (runs / name).rglob("*"):
            if path.is_file():
                sources["runs/" + name + "/" + path.relative_to(runs / name).as_posix()] = path
    for path in reviews.rglob("*"):
        if path.is_file():
            sources["runs/review-exports/" + path.relative_to(reviews).as_posix()] = path
    if any(not allowed_name(name) or path.is_symlink() or not path.is_file() for name, path in sources.items()):
        raise BundleError("Bundle input is linked, missing or outside the file allowlist")
    for path in sources.values():
        scan_secrets(path)
    files = {name: {"size": path.stat().st_size, "sha256": digest(path)} for name, path in sorted(sources.items())}
    from core.dataset_cli import verify
    from ui.review_records import import_session, load_run
    validation = {"dataset": verify(data)}
    with closing(sqlite3.connect((data / "search.sqlite3").as_uri() + "?mode=ro", uri=True)) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        allowed = {"metadata", "documents", "questions", "places", "schools", "teachers", "school_teachers", "answers",
                   "answers_fts", "answers_fts_data", "answers_fts_idx", "answers_fts_content",
                   "answers_fts_docsize", "answers_fts_config"}
        if not tables <= allowed:
            raise BundleError("Unexpected database tables; do not publish this dataset")
    loaded = {name: load_run(runs / name, allow_evaluation=True) for name in RUN_NAMES}
    for session in reviews.iterdir():
        if session.is_dir():
            name = next((name for name in RUN_NAMES if session.name.startswith(name + "-")), None)
            if name is None:
                raise BundleError("Unknown original review export")
            import_session(loaded[name], session.name, export_root=reviews)
    validation.update(saved_runs=len(loaded), review_exports=len(list(reviews.iterdir())))
    with archive.open("xb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|") as target:
                for name, path in sorted(sources.items()):
                    info = tarfile.TarInfo(name)
                    info.size, info.mode, info.mtime = path.stat().st_size, 0o600, 0
                    with path.open("rb") as source:
                        target.addfile(info, source)
    if archive.stat().st_size >= 100 * 1024**2:
        raise BundleError("Compressed bundle exceeds GitHub's normal file limit; use a release asset instead")
    if any(digest(path) != files[name]["sha256"] for name, path in sources.items()):
        raise BundleError("A source changed while packaging; preserve this failed output and rebuild separately")
    manifest = {"format": "stapfer-bootstrap-v1", "archive_name": BUNDLE_NAME, "archive_sha256": digest(archive),
        "compressed_bytes": archive.stat().st_size, "unpacked_bytes": sum(row["size"] for row in files.values()),
        "files": files, "validation": validation,
        "source": "Swiss Federal Archives / University of Bern Stapfer edition",
        "source_terms": "https://opendata.swiss/terms-of-use#terms_open",
        "rights": "Code MIT does not relicense archival data, model outputs or human review text.",
        "excluded": ["raw SQL", "modern contributor tables", "credentials", "private .env files", "model weights",
                     "account-specific HF review exports", "old experiment archives", "server logs"]}
    with manifest_path.open("x", encoding="utf-8") as target:
        json.dump(manifest, target, ensure_ascii=False, indent=2)
        target.write("\n")
    print(json.dumps({key: value for key, value in manifest.items() if key != "files"}, indent=2))
    return archive, manifest_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("data-dir", "runs-dir", "original-reviews-dir", "out-dir"):
        parser.add_argument("--" + option, type=Path, required=True)
    args = parser.parse_args()
    package(args.data_dir, args.runs_dir, args.original_reviews_dir, args.out_dir)


if __name__ == "__main__":
    main()
