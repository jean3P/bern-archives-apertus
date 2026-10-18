"""Dataset import/export/search CLI. Explicit execution only; imports never build data."""

import argparse
from contextlib import closing
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

from core.dataset import project, text_hash
from core.policy import POLICY_VERSION, SCHEMA_VERSION, SOURCE_TERMS, SOURCE_URL, SQL_SHA256, public_policy
from core.record_schema import SCHEMAS, export_schema, validate
from core.search import build_index, lookup_source, search_records
from core.sql_dump import read_dump


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path, rows):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify(directory, *, require_success=True):
    directory = Path(directory)
    if require_success:
        marker = json.loads((directory / "_SUCCESS.json").read_text(encoding="utf-8"))
        if marker["source_sha256"] != SQL_SHA256:
            raise ValueError("Wrong source identity in completion marker")
        for name, expected in marker["artifact_sha256"].items():
            if Path(name).name != name or file_hash(directory / name) != expected:
                raise ValueError("Changed/missing completed artifact: " + name)
    report = json.loads((directory / "validation_report.json").read_text(encoding="utf-8"))
    if report["status"] != "validated" and not (not require_success and report["status"] == "prepared"):
        raise ValueError("Build validation was not completed")
    transformations = {}
    for line in (directory / "transformations.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["record_id"] in transformations:
            raise ValueError("Duplicate transformation record")
        transformations[row["record_id"]] = row
    counts, seen = {}, set()
    with closing(sqlite3.connect((directory / "search.sqlite3").resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or connection.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Index integrity/reference check failed")
        for name, schema in SCHEMAS.items():
            count = 0
            with (directory / (name + ".jsonl")).open(encoding="utf-8") as stream:
                for line in stream:
                    row = json.loads(line)
                    validate(row, schema, name)
                    count += 1
                    if name != "answers" and name != "school_teachers":
                        identity = {"documents": "transcription_id", "questions": "question_id",
                                    "schools": "school_id", "places": "place_id", "teachers": "teacher_id"}[name]
                        stored = connection.execute('SELECT payload FROM "' + name + '" WHERE id=?', (row[identity],)).fetchone()
                        if not stored or json.loads(stored[0]) != row:
                            raise ValueError("SQLite/JSONL entity differs: " + name)
                    elif name == "school_teachers":
                        if not connection.execute("SELECT 1 FROM school_teachers WHERE school_id=? AND teacher_id=?",
                                                  (row["school_id"], row["teacher_id"])).fetchone():
                            raise ValueError("Missing teacher/school relation")
                    if name in ("documents", "answers"):
                        school_ids = [value[0] for value in connection.execute(
                            "SELECT id FROM schools WHERE transcription_id=? ORDER BY id", (row["transcription_id"],))]
                        if school_ids != row["school_ids"]:
                            raise ValueError("Document-context school links differ")
                    if name == "documents":
                        answer_ids = [value[0] for value in connection.execute(
                            "SELECT id FROM answers WHERE transcription_id=? ORDER BY id", (row["transcription_id"],))]
                        if answer_ids != row["answer_ids"]:
                            raise ValueError("Document answer links differ")
                    if name == "answers":
                        record_id = row["record_id"]
                        if record_id in seen:
                            raise ValueError("Duplicate exported answer")
                        seen.add(record_id)
                        transformation = transformations[record_id]
                        if transformation["original_sha256"] != text_hash(row["text_original"]) or transformation["search_sha256"] != text_hash(row["text_search"]):
                            raise ValueError("Text serialization hash differs")
                        stored = connection.execute("SELECT payload FROM answers WHERE id=?", (row["answer_id"],)).fetchone()
                        if not stored or json.loads(stored[0]) != row:
                            raise ValueError("SQLite/JSONL answer differs")
            counts[name] = count
            if connection.execute('SELECT count(*) FROM "' + name + '"').fetchone()[0] != count:
                raise ValueError("SQLite/export entity counts differ: " + name)
        if seen != set(transformations):
            raise ValueError("Transformation coverage differs")
        indexed = connection.execute("SELECT count(*) FROM answers_fts").fetchone()[0]
    if counts != report["exported_counts"] or indexed != report["indexable_answers"]:
        raise ValueError("Reported export/index counts differ")
    with (directory / "answers.tsv").open(encoding="utf-8", newline="") as stream:
        tsv = csv.DictReader(stream, delimiter="\t")
        tsv_count, tsv_ids = 0, set()
        for row in tsv:
            if row["record_id"] in tsv_ids:
                raise ValueError("Duplicate TSV answer")
            tsv_ids.add(row["record_id"])
            original = json.loads(row["text_original_json"])
            if text_hash(original) != transformations[row["record_id"]]["original_sha256"]:
                raise ValueError("TSV text roundtrip differs")
            tsv_count += 1
    if tsv_count != counts["answers"] or tsv_ids != seen:
        raise ValueError("TSV coverage differs")
    return {"status": "verified", "exported_counts": counts, "indexable_answers": indexed,
            "answer_text_roundtrips": len(seen), "model_calls": 0}


def build(source, output, transcription_id=None):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output == source.parent or source.parent in output.parents:
        raise ValueError("Do not place derived output inside the raw input directory")
    output.mkdir(parents=True, exist_ok=False)
    tick = time.perf_counter()
    try:
        print("1/4 Verifying and reading the pinned SQL archive", flush=True)
        dump = read_dump(source)
        parsed = time.perf_counter()
        print("2/4 Applying the public-field policy and requested scope", flush=True)
        rows, transformations, report = project(dump, transcription_id)
        projected = time.perf_counter()
        if not rows["documents"] or not rows["answers"] or not report["indexable_answers"]:
            raise ValueError("Projection has no useful source passages; no success marker will be written")
        print("3/4 Writing exports and the local SQLite FTS5 index", flush=True)
        for name, records in rows.items():
            write_jsonl(output / (name + ".jsonl"), records)
        write_jsonl(output / "transformations.jsonl", transformations)
        with (output / "answers.tsv").open("x", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, delimiter="\t")
            writer.writerow(["record_id", "transcription_id", "question_number_json", "text_original_json", "archive_reference_json"])
            for row in rows["answers"]:
                writer.writerow([row["record_id"], row["transcription_id"], json.dumps(row["question_number"], ensure_ascii=False),
                                 json.dumps(row["text_original"], ensure_ascii=False),
                                 json.dumps(row["archive_reference"], ensure_ascii=False)])
        write_json(output / "schema.json", export_schema())
        write_json(output / "public_policy.json", public_policy())
        build_index(output / "search.sqlite3", rows, dump.sha256)
        indexed = time.perf_counter()
        if file_hash(source) != dump.sha256:
            raise ValueError("Source changed during build")
        originals = {row["id_antwort"]: row["antwort"] for row in dump.tables["t_antwort"]}
        if any(row["text_original"] != originals[row["answer_id"]] for row in rows["answers"]):
            raise ValueError("Original text differs from decoded source")
        try:
            revision = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                                      cwd=Path(__file__).resolve().parents[1], check=False)
            code_commit = revision.stdout.strip() if revision.returncode == 0 else None
        except OSError:
            code_commit = None
        write_json(output / "source_manifest.json", {
            "source_sha256": dump.sha256, "source_member": dump.member,
            "source_url": SOURCE_URL, "source_terms": SOURCE_TERMS,
            "source_credit": "Stapfer-Enquête scholarly edition; University of Bern / Swiss Federal Archives",
            "policy_version": POLICY_VERSION, "schema_version": SCHEMA_VERSION,
            "code_commit": code_commit,
            "implementation_sha256": {"core/" + name + ".py": file_hash(Path(__file__).parent / (name + ".py"))
                for name in ("dataset_cli", "policy", "sql_dump", "dataset", "record_schema", "search", "service")},
            "python": sys.version, "built_at_utc": datetime.now(timezone.utc).isoformat(),
            "scope": report["scope"], "selected_transcription_id": transcription_id,
            "model_calls": 0, "source_sql_executed": False,
        })
        report.update(status="prepared", raw_text_roundtrip_checked=True,
            timing_seconds={"read_parse": parsed - tick, "projection": projected - parsed,
                            "exports_index": indexed - projected})
        write_json(output / "validation_report.json", report)
        print("4/4 Checking serialized records, text roundtrips and references", flush=True)
        verification = verify(output, require_success=False)
        report.update(status="validated", verification=verification)
        report["timing_seconds"]["total"] = time.perf_counter() - tick
        write_json(output / "validation_report.json", report)
        artifacts = {path.name: file_hash(path) for path in sorted(output.iterdir()) if path.is_file()}
        write_json(output / "_SUCCESS.json", {"source_sha256": dump.sha256, "artifact_sha256": artifacts,
                                               "status": "completed", "model_calls": 0})
        return report
    except Exception as error:
        # Do not log raw private SQL values or present partial output as a usable dataset.
        if (output / "validation_report.json").is_file():
            partial = json.loads((output / "validation_report.json").read_text(encoding="utf-8"))
            partial["status"] = "failed"
            write_json(output / "validation_report.json", partial)
        write_json(output / "_FAILED.json", {"status": "failed", "error_type": type(error).__name__,
            "message": str(error), "model_calls": 0, "completion_marker_written": False})
        raise


def main():
    parser = argparse.ArgumentParser(description="CPU-only public import, exports and search; no model calls")
    sub = parser.add_subparsers(dest="command", required=True)
    importer = sub.add_parser("build")
    importer.add_argument("--source", type=Path, required=True)
    importer.add_argument("--out", type=Path, required=True)
    importer.add_argument("--transcription-id", type=int)
    checker = sub.add_parser("verify")
    checker.add_argument("--data-dir", type=Path, required=True)
    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--data-dir", type=Path, required=True)
    search.add_argument("--transcription-id", type=int)
    search.add_argument("--place")
    search.add_argument("--canton-1799")
    search.add_argument("--question-code")
    search.add_argument("--limit", type=int, default=20)
    lookup = sub.add_parser("lookup")
    lookup.add_argument("record_id")
    lookup.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "build":
            result = build(args.source, args.out, args.transcription_id)
        elif args.command == "verify":
            result = verify(args.data_dir)
        elif args.command == "lookup":
            result = lookup_source(args.record_id, data_dir=args.data_dir)
        else:
            result = search_records(args.query, args.transcription_id, place=args.place,
                canton_1799=args.canton_1799, question_code=args.question_code,
                limit=args.limit, data_dir=args.data_dir)
    except (ValueError, LookupError, OSError, sqlite3.Error) as error:
        parser.exit(1, "Dataset command failed: " + str(error) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
