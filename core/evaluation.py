"""Explicit, sequential J4 acquisition and offline review. Importing runs nothing."""

from datetime import datetime, timezone
from pathlib import Path
import platform
import shutil
import subprocess
import time

from core.config import ROOT
from core.evaluation_records import (create_output, digest, load_bundle, read_jsonl,
    seal_directory, value_hash, verify_directory, write_json, write_jsonl)
from core.evaluation_scoring import (aggregate, apply_reviews, document_scores,
    inspect_case, load_reviews, review_template)


def snapshot_code(output):
    files = [*sorted((ROOT / "core").glob("*.py")), ROOT / "contracts.py", ROOT / "pyproject.toml", ROOT / "uv.lock"]
    hashes = {}
    for source in files:
        relative = source.relative_to(ROOT)
        target = output / "code-snapshot" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        hashes[relative.as_posix()] = digest(target)
        if digest(source) != hashes[relative.as_posix()]:
            raise ValueError("Candidate source changed during snapshot")
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                text=True, timeout=10, check=False)
        revision = result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        revision = None
    return {"git_commit": revision, "source_sha256": hashes, "python": platform.python_version(),
            "platform": platform.platform(), "uncommitted_bytes_preserved_in_snapshot": True}


def snapshot_references(bundle, output):
    target = output / "references"
    target.mkdir()
    names = ["reference-manifest.json", *bundle["manifest"]["artifact_sha256"]]
    for name in names:
        source = bundle["directory"] / name
        shutil.copyfile(source, target / name)
        expected = bundle["manifest_sha256"] if name == "reference-manifest.json" else bundle["manifest"]["artifact_sha256"][name]
        if digest(target / name) != expected or digest(source) != expected:
            raise ValueError("Reference changed during snapshot")


def audit_template(bundle, run_manifest):
    return [{"transcription_id": identity, "stratum": stratum,
        "review_binding": value_hash({"transcription_id": identity, "stratum": stratum,
            "reference_manifest_sha256": bundle["manifest_sha256"], "candidate": run_manifest["candidate"],
            "dataset_completion_sha256": run_manifest["dataset_completion_sha256"]}),
        "reviewer": None, "correct_projection": None, "structural_error": None, "notes": ""}
        for stratum, identities in bundle["audit"]["strata"].items() for identity in identities]


def save_scores(output, records, document_template, *, reviews=None, document_reviews=None, metadata):
    judged = apply_reviews(records, load_reviews(reviews, records))
    documents, audit = document_scores(document_template, document_reviews)
    metrics = aggregate(judged)
    metrics.update(document_audit=audit, provenance=metadata,
        document_accuracy=audit["correctly_processed_rate"], structural_error_rate=audit["structural_error_rate"])
    write_jsonl(output / "case-scores.jsonl", judged)
    write_jsonl(output / "document-scores.jsonl", documents)
    write_json(output / "metrics.json", metrics)
    message = ("# J4 evaluation records\n\n"
        f"Authority: {metadata['authority']}. Reference review: {metadata['reference_review']['status']}.\n\n"
        f"Scheduled: {metrics['scheduled_questions']}; attempted: {metrics['attempted']}; "
        f"technical completions: {metrics['technical_completions']}.\n\n"
        f"Confirmed correct: {metrics['confirmed_correct']}; confirmed incorrect: {metrics['confirmed_incorrect']}; "
        f"pending or uncertain: {metrics['pending_or_uncertain']}. "
        f"Question accuracy: {metrics['question_accuracy']} (null until all cases have a verdict).\n\n"
        f"Generation POST attempts: {metrics['generation_posts_attempted']}; validation retries: {metrics['format_retries']}.\n\n"
        f"Document audit: {audit['reviewed']}/{audit['planned']} reviewed. "
        "A selected sample is not a completed audit. Document targets and chatbot accuracy are separate.\n\n"
        "Mechanical status/quote checks do not certify meaning. Draft references and software fixtures "
        "are not independent human-approved model benchmarks. Errors and unstarted cases retain their denominators. "
        "Model startup and device memory were not measured; database records are not scan pages.\n")
    with (output / "report.md").open("x", encoding="utf-8") as stream:
        stream.write(message)
    return metrics


def run_evaluation(references, split, data_dir, out, *, allow_draft=False, reviewed_by=None,
                   _answerer=None, _dataset_verifier=None, pipeline="apertus"):
    """Test-only adapters are explicitly labelled software_fixture, never actual inference."""
    if pipeline not in ("apertus", "apertus-qualified", "qwen-only", "apertus-facets", "qwen-apertus"):
        raise ValueError("Choose apertus, apertus-qualified, qwen-only, apertus-facets or qwen-apertus")
    max_posts = 4 if pipeline == "qwen-apertus" else 3
    bundle = load_bundle(references, split)
    if allow_draft and reviewed_by is not None:
        raise ValueError("Choose a draft diagnostic or an explicit reference-review attestation")
    if reviewed_by is not None and (not isinstance(reviewed_by, str) or not reviewed_by.strip()):
        raise ValueError("A reference reviewer name must be nonempty")
    approved = bool(bundle["manifest"].get("human_reference_approval") or reviewed_by)
    if not approved and not allow_draft:
        raise ValueError("References are draft: use --allow-draft-references for diagnostics, or --reviewed-by only after review")
    if (_answerer is None) != (_dataset_verifier is None):
        raise ValueError("Software fixtures require both explicit adapters")
    authority = "actual_http" if _answerer is None else "software_fixture"
    reference_review = {"status": "review_attested" if approved else "draft_diagnostic",
        "reviewed_by": reviewed_by, "manifest_declared_human_approval": bundle["manifest"].get("human_reference_approval", False),
        "manifest_sha256": bundle["manifest_sha256"], "attestation_is_not_automated_historical_verification": True}
    data_dir = Path(data_dir).resolve()
    output = create_output(out, (data_dir, bundle["directory"]))
    batch_started = time.perf_counter()
    try:
        snapshot_references(bundle, output)
        candidate = snapshot_code(output)
        if authority == "actual_http":
            from core.answering import run_answer
            from core.config import settings, qwen_settings
            from core.dataset_cli import verify
            answerer, verifier = run_answer, verify
            config = qwen_settings() if pipeline == "qwen-only" else settings()
            if pipeline == "qwen-apertus":
                from core.config import qwen_settings
                qwen_config = qwen_settings()
        else:
            answerer, verifier, config = _answerer, _dataset_verifier, None
        verification_started = time.perf_counter()
        verification = verifier(data_dir)
        if not isinstance(verification, dict) or verification.get("status") != "verified":
            raise ValueError("Existing dataset did not verify; no questions may be acquired")
        verification_seconds = time.perf_counter() - verification_started
        write_json(output / "dataset-verification.json", verification)
        manifest = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "split": split,
            "authority": authority, "reference_review": reference_review, "candidate": candidate,
            "reference_manifest_sha256": bundle["manifest_sha256"],
            "dataset_completion_sha256": digest(data_dir / "_SUCCESS.json"),
            "scheduled_case_ids": [case["case_id"] for case in bundle["cases"]],
            "pipeline": pipeline,
            "max_generation_posts": max_posts * len(bundle["cases"]), "max_posts_per_case": max_posts,
            "max_validation_retries_per_case": 1, "runtime_fields": ["question", "transcription_id"],
            "dataset_verification_seconds": verification_seconds,
            "settings": {"model": config.model, "base_url": config.base_url, "timeout": config.timeout,
                         "temperature": 0, "query_rewrite": True} if config else {"software_fixture": True}}
        if pipeline == "qwen-apertus" and config:
            manifest["settings"]["question_evidence_model"] = {"model": qwen_config.model,
                "base_url": qwen_config.base_url, "timeout": qwen_config.timeout}
        write_json(output / "run-manifest.json", manifest)
        if config and pipeline in ("apertus-qualified", "qwen-only", "apertus-facets"):
            from core.apertus import ApertusClient
            from core.answer_qualifications import MODEL, QWEN_MODEL
            if config.model != (QWEN_MODEL if pipeline == "qwen-only" else MODEL):
                raise ValueError("The selected cited-answer pipeline requires its pinned model")
            connection = ApertusClient(config)
            try:
                models = connection.models()
                write_json(output / "serving-preflight.json", {"models": models, "generation_posts": 0})
            except Exception as error:
                raise ValueError("Selected model endpoint is unavailable; batch was not started") from error
            finally:
                connection.close()
        (output / "cases").mkdir()
        records, observations, stop = [], [], None
        # No outer retry: the selected backend owns its declared shared repair allowance.
        for case in bundle["cases"]:
            directory = output / "cases" / case["case_id"]
            observation = {"case_id": case["case_id"], "attempted": stop is None,
                           "response": None, "reason": stop}
            if stop is None:
                started = time.perf_counter()
                try:
                    request = dict(case["input"])
                    options = {}
                    if pipeline in ("apertus-qualified", "qwen-only", "apertus-facets", "qwen-apertus"):
                        options["pipeline"] = pipeline
                        if config and pipeline == "qwen-apertus":
                            options["qwen_config"] = qwen_config
                    response, returned = answerer(request["question"], request["transcription_id"],
                        data_dir=data_dir, out=directory, config=config, **options)
                    if Path(returned).resolve() != directory.resolve():
                        raise ValueError("Backend returned another case's run directory")
                    observation["response"] = response
                except (Exception, KeyboardInterrupt) as error:
                    stop = "backend_exception_" + type(error).__name__
                    observation["reason"] = stop
                observation["wrapper_seconds"] = time.perf_counter() - started
            record = inspect_case(case, directory, observation, bundle["aliases"], authority, pipeline=pipeline)
            if observation["attempted"] and not record["protocol_valid"]:
                stop = stop or "receipt_or_budget_guard"
            records.append(record)
            observations.append(observation)
            # Durable per-case records survive an interrupted later case.
            write_json(output / ("observation-" + case["case_id"] + ".json"), observation)
            write_json(output / ("score-" + case["case_id"] + ".json"), record)
            print(f"[{len(records)}/{len(bundle['cases'])}] {case['case_id']}: {record['observed_status']}", flush=True)
        write_jsonl(output / "case-observations.jsonl", observations)
        write_jsonl(output / "review-template.jsonl", review_template(records))
        document_template = audit_template(bundle, manifest)
        write_jsonl(output / "document-review-template.jsonl", document_template)
        metadata = {"authority": authority, "reference_review": reference_review,
                    "batch_state": "aborted" if stop else "recorded", "stop_reason": stop,
                    "elapsed_before_scoring_seconds": time.perf_counter() - batch_started}
        if digest(data_dir / "_SUCCESS.json") != manifest["dataset_completion_sha256"]:
            raise ValueError("Dataset completion receipt changed during evaluation")
        if any(digest(ROOT / name) != checksum for name, checksum in candidate["source_sha256"].items()):
            raise ValueError("Candidate code changed during evaluation; preserve partial records")
        metrics = save_scores(output, records, document_template, metadata=metadata)
        seal_directory(output, metadata["batch_state"])
        return metrics
    except Exception as error:
        write_json(output / "_FAILED.json", {"error_type": type(error).__name__,
            "message": "Evaluation preparation or record inspection failed; preserve this directory. No retry was started."})
        raise


def score_evaluation(run, out, *, reviews=None, document_reviews=None):
    """Network-free rescore into a new directory; original run and gold stay read-only."""
    run = Path(run).resolve()
    verify_directory(run)
    from core.evaluation_records import read_json
    manifest = read_json(run / "run-manifest.json")
    pipeline = manifest.get("pipeline", "apertus")
    if pipeline not in ("apertus", "apertus-qualified", "qwen-only", "apertus-facets", "qwen-apertus"):
        raise ValueError("Unknown acquired pipeline")
    expected_cap = 4 if pipeline == "qwen-apertus" else 3
    if manifest["max_posts_per_case"] != expected_cap or manifest["max_validation_retries_per_case"] != 1:
        raise ValueError("Acquired pipeline budget differs from its declared policy")
    bundle = load_bundle(run / "references", manifest["split"])
    if bundle["manifest_sha256"] != manifest["reference_manifest_sha256"]:
        raise ValueError("Original run's reference binding differs")
    observations = read_jsonl(run / "case-observations.jsonl")
    if [row["case_id"] for row in observations] != manifest["scheduled_case_ids"] or manifest["scheduled_case_ids"] != [row["case_id"] for row in bundle["cases"]]:
        raise ValueError("Scheduled cases changed or disappeared")
    records = [inspect_case(case, run / "cases" / case["case_id"], observation,
               bundle["aliases"], manifest["authority"], pipeline=pipeline)
               for case, observation in zip(bundle["cases"], observations)]
    document_template = read_jsonl(run / "document-review-template.jsonl")
    # Validate human files before reserving an output directory.
    load_reviews(reviews, records)
    document_scores(document_template, document_reviews)
    protected = [run, *([Path(reviews)] if reviews else []), *([Path(document_reviews)] if document_reviews else [])]
    output = create_output(out, protected)
    metadata = {"authority": manifest["authority"], "reference_review": manifest["reference_review"],
        "input_run_marker_sha256": digest(run / "_COMPLETE.json"),
        "scoring_source_sha256": {name: digest(ROOT / "core" / name) for name in
            ("evaluation.py", "evaluation_records.py", "evaluation_scoring.py")},
        "batch_state": "offline_scored", "reviews_sha256": digest(reviews) if reviews else None,
        "document_reviews_sha256": digest(document_reviews) if document_reviews else None}
    if reviews:
        shutil.copyfile(reviews, output / "submitted-reviews.jsonl")
    if document_reviews:
        shutil.copyfile(document_reviews, output / "submitted-document-reviews.jsonl")
    submitted = output / "submitted-reviews.jsonl" if reviews else None
    document_submitted = output / "submitted-document-reviews.jsonl" if document_reviews else None
    if ((submitted and digest(submitted) != metadata["reviews_sha256"])
            or (document_submitted and digest(document_submitted) != metadata["document_reviews_sha256"])):
        raise ValueError("Human review changed during copying")
    metrics = save_scores(output, records, document_template, reviews=submitted,
                         document_reviews=document_submitted, metadata=metadata)
    verify_directory(run)
    if digest(run / "_COMPLETE.json") != metadata["input_run_marker_sha256"]:
        raise ValueError("Original run changed during scoring")
    seal_directory(output, "offline_scored")
    return metrics
