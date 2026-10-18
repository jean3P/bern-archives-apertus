"""Reference validation and immutable evaluation records. No import-time execution."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from core.config import ROOT
from core.policy import SQL_SHA256

CASE_FILES = {"development": "development-questions.jsonl", "evaluation": "evaluation-questions.jsonl"}


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def value_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    allow_nan=False).encode("utf-8")).hexdigest()


def strict_loads(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate evaluation JSON key")
            result[key] = value
        return result
    def invalid(_):
        raise ValueError("Nonfinite evaluation JSON value")
    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)


def read_json(path):
    return strict_loads(Path(path).read_text(encoding="utf-8"))


def read_jsonl(path):
    with Path(path).open(encoding="utf-8") as stream:
        return [strict_loads(line) for line in stream if line.strip()]


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def write_jsonl(path, values):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        for value in values:
            stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
            stream.flush()


def child_file(root, name):
    if not isinstance(name, str):
        raise ValueError("Unsafe evaluation artifact path")
    name_path = PurePosixPath(name)
    if ("\\" in name or name_path.is_absolute()
            or ".." in name_path.parts or ":" in name or not name_path.parts):
        raise ValueError("Unsafe evaluation artifact path")
    root = Path(root).resolve()
    path = root.joinpath(*name_path.parts)
    if path.is_symlink() or root not in path.resolve().parents or not path.is_file():
        raise ValueError("Missing, external or linked evaluation artifact")
    return path


def load_bundle(directory, split):
    directory = Path(directory).resolve()
    if split not in CASE_FILES:
        raise ValueError("Choose development or evaluation")
    manifest = read_json(directory / "reference-manifest.json")
    if type(manifest.get("human_reference_approval")) is not bool:
        raise ValueError("Reference approval must be an explicit boolean")
    if manifest["source"]["sha256"] != SQL_SHA256:
        raise ValueError("Reference corpus differs from the pinned public source")
    hashes = manifest["artifact_sha256"]
    required = set(CASE_FILES.values()) | {"document-audit-sample.json", "equivalent-source-records.json"}
    if not required <= set(hashes):
        raise ValueError("Reference manifest omits a required artifact")
    for name, expected in hashes.items():
        if PurePosixPath(name).name != name or not re.fullmatch(r"[a-f0-9]{64}", expected):
            raise ValueError("Invalid reference hash entry")
        if digest(child_file(directory, name)) != expected:
            raise ValueError("Changed reference artifact: " + name)
    all_cases, seen = {}, set()
    allowed_dossiers = {}
    for name, filename in CASE_FILES.items():
        rows = read_jsonl(directory / filename)
        if not 1 <= len(rows) <= 50 or len(rows) != manifest["splits"][name]["cases"]:
            raise ValueError("Reference case count differs from manifest")
        dossiers = manifest["splits"][name]["reference_dossiers"]
        if any(type(value) is not int or value < 1 for value in dossiers):
            raise ValueError("Invalid reference dossier")
        allowed_dossiers[name] = set(dossiers)
        for row in rows:
            case_id = row.get("case_id")
            if not isinstance(case_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", case_id) or case_id in seen:
                raise ValueError("Unsafe or repeated case ID")
            seen.add(case_id)
            request = row["input"]
            if set(request) != {"question", "transcription_id"}:
                raise ValueError("Only question and transcription_id may enter the backend")
            if not isinstance(request["question"], str) or not 1 <= len(request["question"].strip()) <= 2000:
                raise ValueError("Invalid evaluation question")
            selected = request["transcription_id"]
            if selected is not None and (type(selected) is not int or selected not in allowed_dossiers[name]):
                raise ValueError("Evaluation scope is outside its reference split")
            if row["expected_status"] not in ("answered", "insufficient_evidence"):
                raise ValueError("Technical errors cannot be expected correct nonanswers")
            if not isinstance(row["required_facts"], list) or any(not isinstance(fact, str) for fact in row["required_facts"]):
                raise ValueError("Invalid reference facts")
            if row["expected_status"] == "answered" and not row["required_facts"]:
                raise ValueError("An answerable reference needs facts")
            if not isinstance(row["evidence"], list) or not row["evidence"]:
                raise ValueError("Reference evidence is required")
            for evidence in row["evidence"]:
                if (type(evidence["answer_id"]) is not int or evidence["answer_id"] < 1
                        or not isinstance(evidence["quote"], str) or len(evidence["quote"].strip()) < 3):
                    raise ValueError("Invalid source reference")
        all_cases[name] = sorted(rows, key=lambda row: row["case_id"])
    if allowed_dossiers["development"] & allowed_dossiers["evaluation"]:
        raise ValueError("Development/evaluation reference dossiers overlap")
    aliases = read_json(directory / "equivalent-source-records.json")
    by_case = {case["case_id"]: case for rows in all_cases.values() for case in rows}
    seen_aliases = set()
    for entry in aliases["alternatives"]:
        case = by_case[entry["case_id"]]
        key = (entry["case_id"], entry["base_answer_id"])
        if key in seen_aliases:
            raise ValueError("Repeated scoped alternate-source mapping")
        seen_aliases.add(key)
        if (entry["base_answer_id"] not in [ref["answer_id"] for ref in case["evidence"]]
                or entry["base_answer_id"] not in entry["accepted_answer_ids"]
                or any(type(value) is not int or value < 1 for value in entry["accepted_answer_ids"])):
            raise ValueError("Invalid scoped alternate-source mapping")
    audit = read_json(directory / "document-audit-sample.json")
    audit_ids = [value for values in audit["strata"].values() for value in values]
    if (audit["source_sha256"] != SQL_SHA256 or len(audit_ids) != audit["sample_size"]
            or len(set(audit_ids)) != len(audit_ids)
            or any(type(value) is not int or value < 1 for value in audit_ids)):
        raise ValueError("Invalid document-audit sample")
    return {"directory": directory, "manifest": manifest, "cases": all_cases[split],
            "aliases": aliases, "audit": audit, "manifest_sha256": digest(directory / "reference-manifest.json")}


def create_output(directory, protected=()):
    directory = Path(directory).resolve()
    if directory.exists():
        raise FileExistsError("Evaluation output already exists")
    if directory == ROOT or directory in ROOT.parents:
        raise ValueError("Do not use a repository root or ancestor as output")
    boundaries = [ROOT / name for name in ("data", ".git", "core", "tests", "ui", "docs", "evaluation")]
    for boundary in [*boundaries, *map(Path, protected)]:
        boundary = boundary.resolve()
        if directory == boundary or boundary in directory.parents or directory in boundary.parents:
            raise ValueError("Evaluation output overlaps protected inputs")
    directory.mkdir(parents=True, exist_ok=False)
    return directory


def seal_directory(directory, status):
    files = {path.relative_to(directory).as_posix(): digest(path)
             for path in sorted(directory.rglob("*")) if path.is_file()}
    write_json(directory / "_COMPLETE.json", {"status": status, "artifact_sha256": files})


def verify_directory(directory):
    directory = Path(directory).resolve()
    marker = read_json(directory / "_COMPLETE.json")
    expected = marker["artifact_sha256"]
    actual = {path.relative_to(directory).as_posix() for path in directory.rglob("*")
              if path.is_file() and path != directory / "_COMPLETE.json"}
    if actual != set(expected):
        raise ValueError("Evaluation artifact inventory changed; keep reviews outside the original run")
    for name, checksum in expected.items():
        if digest(child_file(directory, name)) != checksum:
            raise ValueError("Evaluation artifact changed: " + name)
    return marker
