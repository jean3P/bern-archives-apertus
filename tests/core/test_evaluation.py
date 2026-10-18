"""Offline software fixtures, not archival or model-quality measurements."""

from copy import deepcopy
import json

import pytest

from core.evaluation import run_evaluation, score_evaluation
from core.evaluation_records import (create_output, digest, load_bundle, read_json,
    read_jsonl, strict_loads, verify_directory, write_json, write_jsonl)
from core.evaluation_scoring import accepted_ids, document_scores
from core.evidence import format_answer, make_packet
from core.policy import SQL_SHA256


def example(case_id, transcription, *, nonanswer=False):
    return {"case_id": case_id, "topic": "synthetic",
        "input": {"question": "Unsupported precision?" if nonanswer else "What place?",
                  "transcription_id": transcription},
        "expected_status": "insufficient_evidence" if nonanswer else "answered",
        "required_facts": [] if nonanswer else ["Testville"],
        "evidence": [{"answer_id": 901, "quote": "Testville is the place."}]}


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    # A test must fail before opening any real HTTP connection.
    def forbidden(*args, **kwargs):
        raise AssertionError("Network is forbidden in evaluation software tests")
    monkeypatch.setattr("httpx.Client.send", forbidden)
    references = tmp_path / "references"
    references.mkdir()
    write_jsonl(references / "development-questions.jsonl",
                [example("DEV-01", 101), example("DEV-02", 101, nonanswer=True)])
    write_jsonl(references / "evaluation-questions.jsonl", [example("EVAL-01", 202)])
    write_json(references / "equivalent-source-records.json", {"alternatives": []})
    write_json(references / "document-audit-sample.json", {"source_sha256": SQL_SHA256,
        "sample_size": 100, "strata": {"stratum-" + str(i): list(range(i * 20 + 1, i * 20 + 21)) for i in range(5)}})
    files = sorted(path.name for path in references.iterdir())
    write_json(references / "reference-manifest.json", {"source": {"sha256": SQL_SHA256},
        "human_reference_approval": False,
        "artifact_sha256": {name: digest(references / name) for name in files},
        "splits": {"development": {"cases": 2, "reference_dossiers": [101]},
                   "evaluation": {"cases": 1, "reference_dossiers": [202]}}})
    data = tmp_path / "dataset"
    data.mkdir()
    write_json(data / "_SUCCESS.json", {"source_sha256": SQL_SHA256, "software_fixture": True})
    return references, data


def rewrite_fixture(path, value):
    # Test corruption only: application record writers remain exclusive-create.
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def refresh_fixture_hashes(references):
    path = references / "reference-manifest.json"
    manifest = read_json(path)
    manifest["artifact_sha256"] = {name: digest(references / name) for name in manifest["artifact_sha256"]}
    rewrite_fixture(path, manifest)


def fixture_answerer(seen, *, mutate=None):
    def acquire(question, transcription_id, *, data_dir, out, config):
        seen.append({"question": question, "transcription_id": transcription_id,
                     "keyword_fields": ["data_dir", "out", "config"]})
        out.mkdir()
        record = {"record_id": "stapfer:answer:901", "question_id": 1, "question_number": "I.1",
            "transcription_id": transcription_id, "text_original": "Testville is the place.",
            "archive_reference": "SYNTHETIC ARCHIVE", "pdf_page_index": None,
            "school_ids": [], "school_assignment_source_raw": None, "quality_flags": []}
        catalogue = [{"question_id": 1, "text_original": "Place?", "text_french": None}]
        packet, included, _ = make_packet([record], catalogue)
        value = {"status": "answered", "claims": [{"text": "The place is Testville.",
            "citations": [{"record_id": record["record_id"], "quote": record["text_original"]}]}], "message": ""}
        if question == "Unsupported precision?":
            value = {"status": "insufficient_evidence", "claims": [],
                     "message": "The supplied passage does not establish that precision."}
        response = format_answer(value, included)
        card = {key: record[key] for key in ("record_id", "transcription_id", "question_number",
                                            "text_original", "archive_reference", "pdf_page_index")}
        write_json(out / "input.json", {"question": question, "transcription_id": transcription_id})
        write_json(out / "retrieved_sources.json", [card])
        write_json(out / "evidence.json", {"packet": packet})
        write_json(out / "validated_claims.json", value)
        write_json(out / "response.json", response)
        write_json(out / "summary.json", {"status": response["status"], "transport": "mock_transport",
            "generation_posts_attempted": 1, "format_retries": 0,
            "timing_seconds": {"total_seconds": 0.25}})
        write_jsonl(out / "events.jsonl", [{"event": "generation_request", "request": {"question": question}},
            {"event": "generation_response", "body": json.dumps({"usage": {"prompt_tokens": 20, "completion_tokens": 10}})}])
        if mutate:
            mutate(out, response)
        return response, out
    return acquire


def acquire_fixture(prepared, tmp_path, *, mutate=None, **kwargs):
    references, data = prepared
    seen = []
    output = tmp_path / "run"
    metrics = run_evaluation(references, "development", data, output,
        allow_draft=True, _answerer=fixture_answerer(seen, mutate=mutate),
        _dataset_verifier=lambda path: {"status": "verified", "software_fixture": True}, **kwargs)
    return output, metrics, seen


def test_packaged_draft_is_hash_checked_but_not_human_gold():
    from core.config import ROOT
    bundle = load_bundle(ROOT / "evaluation/references/draft-v1", "evaluation")
    assert len(bundle["cases"]) == 30 and bundle["manifest"]["human_reference_approval"] is False
    assert bundle["audit"]["sample_size"] == 100


def test_gold_fields_do_not_enter_backend_and_quotes_do_not_grant_correctness(prepared, tmp_path):
    output, metrics, seen = acquire_fixture(prepared, tmp_path)
    assert all(set(request) == {"question", "transcription_id", "keyword_fields"} for request in seen)
    assert metrics["attempted"] == 2 and metrics["technical_completions"] == 2
    assert metrics["confirmed_correct"] == 0 and metrics["pending_or_uncertain"] == 2
    assert metrics["question_accuracy"] is None
    assert metrics["citation_integrity"]["mechanically_valid_answers"] == 1
    assert metrics["nonanswers"]["nonempty_packets"] == 1
    assert metrics["document_audit"]["reviewed"] == 0 and metrics["document_accuracy"] is None
    assert metrics["provenance"]["authority"] == "software_fixture"
    assert read_json(output / "run-manifest.json")["max_generation_posts"] == 6
    verify_directory(output)


def test_draft_is_blocked_before_output_or_model(prepared, tmp_path):
    references, data = prepared
    with pytest.raises(ValueError, match="draft"):
        run_evaluation(references, "development", data, tmp_path / "blocked")
    assert not (tmp_path / "blocked").exists()


def test_review_attestation_is_recorded_not_fabricated(prepared, tmp_path):
    references, data = prepared
    output = tmp_path / "attested"
    run_evaluation(references, "development", data, output, reviewed_by="Test reviewer",
        _answerer=fixture_answerer([]), _dataset_verifier=lambda path: {"status": "verified"})
    review = read_json(output / "run-manifest.json")["reference_review"]
    assert review["reviewed_by"] == "Test reviewer" and review["status"] == "review_attested"
    assert review["manifest_declared_human_approval"] is False


@pytest.mark.parametrize("mutation", ["changed_hash", "extra_input", "unsafe_id", "overlapping_dossiers", "duplicate_alias"])
def test_invalid_references_are_rejected_before_acquisition(prepared, mutation):
    references, _ = prepared
    path = references / "development-questions.jsonl"
    rows = read_jsonl(path)
    if mutation == "changed_hash":
        path.write_text("{}\n", encoding="utf-8")
    elif mutation in ("extra_input", "unsafe_id"):
        if mutation == "extra_input":
            rows[0]["input"]["expected_answer"] = "Testville"
        else:
            rows[0]["case_id"] = "../another-case"
        path.unlink()
        write_jsonl(path, rows)
        refresh_fixture_hashes(references)
    elif mutation == "overlapping_dossiers":
        manifest = read_json(references / "reference-manifest.json")
        manifest["splits"]["evaluation"]["reference_dossiers"].append(101)
        rewrite_fixture(references / "reference-manifest.json", manifest)
    else:
        entry = {"case_id": "DEV-01", "base_answer_id": 901, "accepted_answer_ids": [901, 902]}
        rewrite_fixture(references / "equivalent-source-records.json", {"alternatives": [entry, entry]})
        refresh_fixture_hashes(references)
    with pytest.raises(ValueError):
        load_bundle(references, "development")


@pytest.mark.parametrize("mutation", ["over_budget", "wrong_input", "null_response", "broken_json"])
def test_receipt_guard_keeps_all_denominators_and_stops_further_requests(prepared, tmp_path, mutation):
    def corrupt(directory, response):
        if mutation == "over_budget":
            summary = read_json(directory / "summary.json")
            summary["generation_posts_attempted"] = 4
            rewrite_fixture(directory / "summary.json", summary)
        elif mutation == "wrong_input":
            rewrite_fixture(directory / "input.json", {"question": "Another question", "transcription_id": 101})
        elif mutation == "null_response":
            rewrite_fixture(directory / "response.json", None)
        else:
            (directory / "summary.json").write_text("{broken", encoding="utf-8")
    output, metrics, seen = acquire_fixture(prepared, tmp_path, mutate=corrupt)
    assert len(seen) == 1 and metrics["scheduled_questions"] == 2 and metrics["attempted"] == 1
    assert metrics["confirmed_incorrect"] == 2 and metrics["question_accuracy"] == 0
    assert read_json(output / "_COMPLETE.json")["status"] == "aborted"
    assert len(read_jsonl(output / "case-observations.jsonl")) == 2


def test_backend_exception_does_not_become_historical_absence(prepared, tmp_path):
    references, data = prepared
    def timeout(*args, **kwargs):
        raise TimeoutError("Synthetic interruption")
    output = tmp_path / "timeout"
    metrics = run_evaluation(references, "development", data, output, allow_draft=True,
        _answerer=timeout, _dataset_verifier=lambda path: {"status": "verified"})
    assert metrics["attempted"] == 1 and metrics["confirmed_incorrect"] == 2
    assert metrics["generation_posts_attempted"] is None
    assert all(row["observed_status"] != "insufficient_evidence" for row in read_jsonl(output / "case-scores.jsonl"))


def test_dataset_failure_acquires_nothing(prepared, tmp_path):
    references, data = prepared
    seen = []
    with pytest.raises(ValueError, match="did not verify"):
        run_evaluation(references, "development", data, tmp_path / "bad-data", allow_draft=True,
            _answerer=fixture_answerer(seen), _dataset_verifier=lambda path: {"status": "failed"})
    assert not seen and (tmp_path / "bad-data" / "_FAILED.json").is_file()


def test_offline_review_computes_scores_without_reacquisition(prepared, tmp_path):
    output, _, seen = acquire_fixture(prepared, tmp_path)
    before = digest(output / "_COMPLETE.json")
    reviews = read_jsonl(output / "review-template.jsonl")
    for row in reviews:
        row.update(reviewer="Test reviewer", decision="correct", supported_claims=1 if row["case_id"] == "DEV-01" else 0)
    path = tmp_path / "reviews.jsonl"
    write_jsonl(path, reviews)
    metrics = score_evaluation(output, tmp_path / "scored", reviews=path)
    assert metrics["question_accuracy"] == 1 and metrics["confirmed_correct"] == 2
    assert len(seen) == 2 and digest(output / "_COMPLETE.json") == before
    verify_directory(output)
    verify_directory(tmp_path / "scored")


@pytest.mark.parametrize("mutation", ["wrong_binding", "unknown_case", "duplicate", "no_reviewer", "unchecked_claims"])
def test_unbound_or_incomplete_reviews_cannot_pass(prepared, tmp_path, mutation):
    output, _, _ = acquire_fixture(prepared, tmp_path)
    rows = read_jsonl(output / "review-template.jsonl")[:1]
    rows[0].update(reviewer="Reviewer", decision="correct", supported_claims=1)
    if mutation == "wrong_binding":
        rows[0]["review_binding"] = "0" * 64
    elif mutation == "unknown_case":
        rows[0]["case_id"] = "OTHER"
    elif mutation == "duplicate":
        rows.append(deepcopy(rows[0]))
    elif mutation == "no_reviewer":
        rows[0]["reviewer"] = None
    else:
        rows[0]["supported_claims"] = None
    path = tmp_path / "bad-reviews.jsonl"
    write_jsonl(path, rows)
    with pytest.raises(ValueError):
        score_evaluation(output, tmp_path / "rejected-score", reviews=path)
    assert not (tmp_path / "rejected-score").exists()


def test_original_run_cannot_be_edited_for_review(prepared, tmp_path):
    output, _, _ = acquire_fixture(prepared, tmp_path)
    (output / "review-template.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        score_evaluation(output, tmp_path / "rejected")


def test_wrong_meaning_can_pass_quote_check_but_fail_review(prepared, tmp_path):
    def wrong(directory, response):
        claims = read_json(directory / "validated_claims.json")
        if claims["status"] == "answered":
            claims["claims"][0]["text"] = "There were 500 pupils."
            rewrite_fixture(directory / "validated_claims.json", claims)
            response["answer"] = "There were 500 pupils. [stapfer:answer:901]"
            rewrite_fixture(directory / "response.json", response)
    output, _, _ = acquire_fixture(prepared, tmp_path, mutate=wrong)
    records = read_jsonl(output / "case-scores.jsonl")
    assert records[0]["mechanical_citation_valid"] is True and records[0]["final_correct"] is None
    review = read_jsonl(output / "review-template.jsonl")[0]
    review.update(reviewer="Reviewer", decision="incorrect", supported_claims=0,
                  notes="A location quotation does not establish pupil numbers.")
    path = tmp_path / "meaning-review.jsonl"
    write_jsonl(path, [review])
    result = score_evaluation(output, tmp_path / "meaning-scored", reviews=path)
    assert result["confirmed_incorrect"] == 1 and result["question_accuracy"] is None


def test_invalid_citation_cannot_be_approved_by_a_reviewer(prepared, tmp_path):
    def wrong_quote(directory, response):
        value = read_json(directory / "validated_claims.json")
        if value["status"] == "answered":
            value["claims"][0]["citations"][0]["quote"] = "Invented quotation"
            rewrite_fixture(directory / "validated_claims.json", value)
    output, _, _ = acquire_fixture(prepared, tmp_path, mutate=wrong_quote)
    rows = read_jsonl(output / "case-scores.jsonl")
    assert rows[0]["mechanical_citation_valid"] is False and rows[0]["final_correct"] is False
    review = read_jsonl(output / "review-template.jsonl")[0]
    review.update(reviewer="Reviewer", decision="correct", supported_claims=1)
    path = tmp_path / "invalid-approval.jsonl"
    write_jsonl(path, [review])
    with pytest.raises(ValueError, match="cannot pass"):
        score_evaluation(output, tmp_path / "rejected", reviews=path)


def test_duplicate_equivalence_is_case_and_question_scoped():
    reference = {"answer_id": 104334, "quote": "rien"}
    aliases = {"alternatives": [{"case_id": "EVAL-19", "base_answer_id": 104334,
                                "accepted_answer_ids": [104334, 109346]}]}
    values = accepted_ids({"case_id": "EVAL-19"}, reference, aliases)
    assert "stapfer:answer:109346" in values and "stapfer:answer:104346" not in values
    assert accepted_ids({"case_id": "OTHER"}, reference, aliases) == {"stapfer:answer:104334"}


@pytest.mark.parametrize("errors,meets", [(4, True), (5, False)])
def test_document_target_is_strictly_less_than_five_percent(tmp_path, errors, meets):
    template = [{"transcription_id": i, "stratum": "synthetic", "review_binding": str(i),
        "reviewer": None, "correct_projection": None, "structural_error": None, "notes": ""} for i in range(100)]
    assert document_scores(template)[1]["meets_sample_targets"] is None
    reviews = deepcopy(template)
    for i, row in enumerate(reviews):
        row.update(reviewer="Reviewer", correct_projection=i >= errors, structural_error=i < errors)
    path = tmp_path / "documents.jsonl"
    write_jsonl(path, reviews)
    metrics = document_scores(template, path)[1]
    assert metrics["reviewed"] == 100 and metrics["meets_sample_targets"] is meets


def test_existing_outputs_and_input_directories_are_never_overwritten(prepared, tmp_path):
    references, _ = prepared
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(FileExistsError):
        create_output(existing)
    with pytest.raises(ValueError, match="protected"):
        create_output(references / "nested", (references,))


@pytest.mark.parametrize("text", ['{"a":1,"a":2}', '{"value":NaN}'])
def test_evaluation_json_rejects_duplicate_or_nonfinite_fields(text):
    with pytest.raises(ValueError):
        strict_loads(text)
