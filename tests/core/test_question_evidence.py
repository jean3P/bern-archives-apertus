"""Authored synthetic hybrid controls; no live models, archive references or network."""

from copy import deepcopy
import hashlib
import json

import httpx
import pytest

from core.answering import RunLog, run_answer
from core.config import Settings, qwen_settings
from core import question_evidence as qe
from core.evaluation_scoring import inspect_case
from core.evidence import make_packet
from core.policy import SCHEMA_VERSION, SQL_SHA256
from core.search import build_index

CATALOGUE = [
    {"question_id": 1, "question_number": "I.1", "text_original": "Keeper and family", "text_french": None},
    {"question_id": 2, "question_number": "I.2", "text_original": "Attending learners", "text_french": None}]
TEXT = "The keeper is thirty-one. The keeper has two children."
RECORD = {"record_id": "stapfer:answer:901", "answer_id": 901, "transcription_id": 101,
    "question_id": 1, "question_number": "I.1", "text_original": TEXT, "text_search": TEXT,
    "archive_reference": "SYNTHETIC", "pdf_page_index": None, "school_ids": [],
    "school_assignment_source_raw": None, "quality_flags": []}


def interpretation():
    return {"question_codes": ["I.1"], "queries": [], "ambiguity": "", "facets": [
        {"subject": "keeper", "request": "age", "question_codes": ["I.1"]},
        {"subject": "keeper family", "request": "children count", "question_codes": ["I.1"]}]}


def extraction():
    return {"facets": [
        {"facet_id": "f1", "status": "supported", "fact": "The keeper is thirty-one.",
         "citations": [{"record_id": RECORD["record_id"], "quote": "The keeper is thirty-one."}], "limitation": ""},
        {"facet_id": "f2", "status": "supported", "fact": "The keeper has two children.",
         "citations": [{"record_id": RECORD["record_id"], "quote": "The keeper has two children."}], "limitation": ""}]}


def final():
    return {"status": "answered", "message": "", "claims": [
        {"text": row["fact"], "facet_ids": [row["facet_id"]], "citations": deepcopy(row["citations"])}
        for row in extraction()["facets"]]}


@pytest.fixture(autouse=True)
def deny_real_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Real network is forbidden in hybrid software controls")
    monkeypatch.setattr("httpx.HTTPTransport.handle_request", denied)
    monkeypatch.setattr("core.answering.settings", lambda: Settings())
    monkeypatch.setattr("core.answering.qwen_settings", lambda: Settings(
        base_url="http://127.0.0.1:8012/v1", model=qe.QWEN_MODEL))


@pytest.fixture
def dataset(tmp_path):
    directory = tmp_path / "dataset"
    directory.mkdir()
    rows = {"documents": [{"transcription_id": 101}], "questions": CATALOGUE,
        "answers": [RECORD], "schools": [], "places": [], "teachers": [], "school_teachers": []}
    build_index(directory / "search.sqlite3", rows, SQL_SHA256)
    (directory / "source_manifest.json").write_text(json.dumps({"source_sha256": SQL_SHA256,
        "schema_version": SCHEMA_VERSION}), encoding="utf-8")
    (directory / "_SUCCESS.json").write_text(json.dumps({"status": "completed", "source_sha256": SQL_SHA256,
        "artifact_sha256": {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
            for name in ("source_manifest.json", "search.sqlite3")}}), encoding="utf-8")
    return directory


def wire(replies, seen, *, finish="stop", wrong_model=False):
    replies = iter(replies)
    def handle(request):
        model = qe.QWEN_MODEL if request.url.port == 8012 else qe.APERTUS_MODEL
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": model}]})
        body = json.loads(request.content)
        assert body["model"] == model
        seen.append(body)
        reply = next(replies)
        return httpx.Response(200, json={"model": "wrong" if wrong_model else model,
            "choices": [{"finish_reason": finish, "message": {"content": json.dumps(reply)}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 30}})
    return httpx.MockTransport(handle)


def acquire(dataset, tmp_path, replies, **options):
    seen = []
    response, directory = run_answer("Give the keeper age and family children count", 101,
        data_dir=dataset, out=tmp_path / "answer", pipeline="qwen-apertus",
        transport=wire(replies, seen, **options))
    return response, directory, seen


def test_three_stages_have_correct_models_and_keep_original_ui_contract(dataset, tmp_path):
    before = {path.name: path.read_bytes() for path in dataset.iterdir()}
    response, directory, seen = acquire(dataset, tmp_path, [interpretation(), extraction(), final()])
    assert response["status"] == "answered"
    assert set(response) == {"mode", "status", "answer", "sources", "message"}
    assert [body["model"] for body in seen] == [qe.QWEN_MODEL, qe.QWEN_MODEL, qe.APERTUS_MODEL]
    assert [body["max_tokens"] for body in seen] == [512, 1536, 768]
    assert [body["response_format"]["json_schema"]["name"] for body in seen] == list(qe.STAGE_MODELS)
    summary = json.loads((directory / "summary.json").read_text())
    assert summary["generation_posts_attempted"] == 3 and summary["format_retries"] == 0
    assert set(summary["timing_seconds"]) == {"interpretation_seconds", "retrieval_seconds", "extraction_seconds",
                                              "answer_seconds", "total_seconds"}
    assert (directory / "facet_answer.json").exists() and (directory / "qwen-models.json").exists()
    assert all("facet_ids" not in claim for claim in json.loads((directory / "validated_claims.json").read_text())["claims"])
    assert {path.name: path.read_bytes() for path in dataset.iterdir()} == before


def test_no_reference_fields_enter_any_model_payload(dataset, tmp_path):
    _, _, seen = acquire(dataset, tmp_path, [interpretation(), extraction(), final()])
    for body in seen:
        payload = json.loads(body["messages"][1]["content"])
        assert not {"required_facts", "expected_status", "evidence_answer_ids", "case_id", "review_binding"} & set(payload)
    answer_payload = json.loads(seen[-1]["messages"][1]["content"])
    assert answer_payload["evidence"] and answer_payload["extraction_checklist"] == extraction()


def test_missing_final_facet_gets_only_one_shared_retry(dataset, tmp_path):
    incomplete = final()
    incomplete["claims"] = incomplete["claims"][:1]
    response, directory, seen = acquire(dataset, tmp_path, [interpretation(), extraction(), incomplete, final()])
    assert response["status"] == "answered" and len(seen) == 4
    assert json.loads((directory / "summary.json").read_text())["format_retries"] == 1
    assert "omitted a requested facet" in seen[-1]["messages"][1]["content"]


def test_interpretation_repair_spends_final_stage_allowance(dataset, tmp_path):
    invalid = interpretation()
    invalid["question_codes"] = ["I.99"]
    incomplete = final()
    incomplete["claims"] = incomplete["claims"][:1]
    response, directory, seen = acquire(dataset, tmp_path, [invalid, interpretation(), extraction(), incomplete])
    assert response["status"] == "error" and len(seen) == 4
    assert json.loads((directory / "summary.json").read_text())["format_retries"] == 1
    assert not (directory / "validated_claims.json").exists()


def test_bad_extraction_quote_cannot_reach_writer_without_repair(dataset, tmp_path):
    bad = extraction()
    bad["facets"][0]["citations"][0]["quote"] = "Not in the supplied passage"
    response, directory, seen = acquire(dataset, tmp_path, [interpretation(), bad, bad])
    assert response["status"] == "error" and len(seen) == 3
    assert all(body["model"] == qe.QWEN_MODEL for body in seen)
    assert "exact span" in (directory / "events.jsonl").read_text()


@pytest.mark.parametrize("status", ["missing", "ambiguous", "conflicting"])
def test_unresolved_extraction_reaches_apertus_nonanswer_not_a_fabricated_fact(dataset, tmp_path, status):
    extracted = extraction()
    extracted["facets"][1].update(status=status, fact="", citations=[], limitation="Family count unresolved.")
    decline = {"status": "insufficient_evidence", "claims": [], "message": "Family count remains unresolved in supplied evidence."}
    response, directory, seen = acquire(dataset, tmp_path, [interpretation(), extracted, decline])
    assert response["status"] == "insufficient_evidence" and response["sources"]
    assert seen[-1]["model"] == qe.APERTUS_MODEL
    assert json.loads((directory / "evidence_extraction.json").read_text())["facets"][1]["status"] == status


def test_supported_status_cannot_clear_interpretation_ambiguity(dataset, tmp_path):
    ambiguous = interpretation()
    ambiguous["ambiguity"] = "Family or school population is not specified."
    decline = {"status": "insufficient_evidence", "claims": [], "message": "Please specify the intended population."}
    response, _, seen = acquire(dataset, tmp_path, [ambiguous, extraction(), final(), decline])
    assert response["status"] == "insufficient_evidence" and len(seen) == 4


def test_empty_evidence_does_not_call_extraction_or_writer(dataset, tmp_path):
    unsupported = interpretation()
    unsupported.update(question_codes=[], facets=[{"subject": "room", "request": "exact position", "question_codes": []}])
    response, _, seen = acquire(dataset, tmp_path, [unsupported])
    assert response["status"] == "insufficient_evidence" and response["sources"] == [] and len(seen) == 1


@pytest.mark.parametrize("option", [{"finish": "length"}, {"wrong_model": True}])
def test_truncated_or_wrong_model_reply_is_error_without_hidden_retry(dataset, tmp_path, option):
    response, _, seen = acquire(dataset, tmp_path, [interpretation()], **option)
    assert response["status"] == "error" and len(seen) == 1


def test_subject_and_code_contract_rejects_pupil_quote_for_family_facet():
    pupil = {**RECORD, "record_id": "stapfer:answer:902", "answer_id": 902,
             "question_id": 2, "question_number": "I.2", "text_original": "Twenty learners attend."}
    _, included, _ = make_packet([RECORD, pupil], CATALOGUE)
    extracted = extraction()
    extracted["facets"][1].update(fact="Twenty children.", citations=[
        {"record_id": pupil["record_id"], "quote": pupil["text_original"]}])
    with pytest.raises(ValueError, match="different survey-question"):
        qe.validate_extraction(extracted, qe.bind_facets(interpretation()), included)


def test_well_tagged_wrong_meaning_remains_a_semantic_review_problem():
    _, included, _ = make_packet([RECORD], CATALOGUE)
    wrong = final()
    wrong["claims"][1]["text"] = "The keeper has fifty children."
    assert qe.validate_final(wrong, interpretation(), extraction(), included)["claims"][1]["text"] == "The keeper has fifty children."
    # Documents the check's limit; no semantic-accuracy claim follows from these tests.


@pytest.mark.parametrize("mutation", ["extra_id", "duplicate_facet", "missing_union", "lost_explicit", "scoped_query"])
def test_interpretation_rejects_unknown_extra_or_unbound_fields(mutation):
    value = interpretation()
    explicit = ()
    if mutation == "extra_id":
        value["source_id"] = "stapfer:answer:901"
    elif mutation == "duplicate_facet":
        value["facets"][0]["facet_id"] = "caller IDs are assigned by software"
    elif mutation == "missing_union":
        value["question_codes"].append("I.2")
    elif mutation == "lost_explicit":
        explicit = ("I.2",)
    else:
        value["queries"] = ["school"]
    with pytest.raises(ValueError):
        qe.validate_interpretation(value, CATALOGUE, True, explicit)


def test_existing_output_and_literal_mode_restrictions(dataset, tmp_path):
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(FileExistsError):
        run_answer("Question", 101, pipeline="qwen-apertus", data_dir=dataset, out=existing)
    with pytest.raises(ValueError, match="literal-only"):
        run_answer("Question", 101, pipeline="qwen-apertus", rewrite=False, out=tmp_path / "literal")


def test_hybrid_log_stops_at_four_posts_before_fifth_dispatch(tmp_path):
    log = RunLog(tmp_path / "budget", max_posts=4)
    for _ in range(4):
        log.record({"event": "generation_request"})
    with pytest.raises(ValueError, match="limit"):
        log.record({"event": "generation_request"})
    assert log.calls == 4


def test_qwen_settings_use_independent_key_and_preserve_apertus_default(monkeypatch):
    monkeypatch.setattr("core.config.load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("BERN_APERTUS_API_KEY", "apertus-test-key")
    for key in ("BERN_QWEN_BASE_URL", "BERN_QWEN_MODEL", "BERN_QWEN_TIMEOUT", "BERN_QWEN_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    selected = qwen_settings()
    assert selected.model == qe.QWEN_MODEL and selected.api_key is None
    assert Settings().model == qe.APERTUS_MODEL


def test_offline_inspection_replays_hybrid_and_rejects_stale_extraction(dataset, tmp_path):
    response, directory, _ = acquire(dataset, tmp_path, [interpretation(), extraction(), final()])
    case = {"case_id": "SOFTWARE-1", "topic": "synthetic",
        "input": {"question": "Give the keeper age and family children count", "transcription_id": 101},
        "expected_status": "answered", "evidence": [{"answer_id": 901, "quote": TEXT}]}
    observation = {"attempted": True, "response": response}
    row = inspect_case(case, directory, observation, {"alternatives": []}, "software_fixture", pipeline="qwen-apertus")
    assert row["protocol_valid"] and row["mechanical_citation_valid"] and row["generation_posts_attempted"] == 3
    stale = extraction()
    stale["facets"][0]["fact"] = "Changed after acquisition."
    (directory / "evidence_extraction.json").write_text(json.dumps(stale), encoding="utf-8")
    row = inspect_case(case, directory, observation, {"alternatives": []}, "software_fixture", pipeline="qwen-apertus")
    assert not row["protocol_valid"]


def test_hybrid_evaluator_records_four_post_cap_and_offline_replay(dataset, tmp_path):
    from core.evaluation import run_evaluation, score_evaluation
    from core.evaluation_records import digest, read_json, verify_directory, write_json, write_jsonl
    references = tmp_path / "references"
    references.mkdir()
    case = {"case_id": "SOFTWARE-1", "topic": "synthetic",
        "input": {"question": "Give the keeper age and family children count", "transcription_id": 101},
        "expected_status": "answered", "required_facts": ["Synthetic age and family count"],
        "evidence": [{"answer_id": 901, "quote": TEXT}]}
    write_jsonl(references / "development-questions.jsonl", [case])
    other = {**case, "case_id": "SOFTWARE-2", "input": {**case["input"], "transcription_id": 202}}
    write_jsonl(references / "evaluation-questions.jsonl", [other])
    write_json(references / "equivalent-source-records.json", {"alternatives": []})
    write_json(references / "document-audit-sample.json", {"source_sha256": SQL_SHA256,
        "sample_size": 1, "strata": {"synthetic": [101]}})
    names = [path.name for path in references.iterdir()]
    write_json(references / "reference-manifest.json", {"source": {"sha256": SQL_SHA256},
        "human_reference_approval": False, "artifact_sha256": {name: digest(references / name) for name in names},
        "splits": {"development": {"cases": 1, "reference_dossiers": [101]},
                   "evaluation": {"cases": 1, "reference_dossiers": [202]}}})
    def answerer(question, transcription_id, *, data_dir, out, config, pipeline):
        assert pipeline == "qwen-apertus" and config is None
        return run_answer(question, transcription_id, data_dir=data_dir, out=out, pipeline=pipeline,
            transport=wire([interpretation(), extraction(), final()], []))
    output = tmp_path / "evaluation-run"
    metrics = run_evaluation(references, "development", dataset, output, allow_draft=True,
        pipeline="qwen-apertus", _answerer=answerer, _dataset_verifier=lambda _: {"status": "verified"})
    assert metrics["technical_completions"] == 1 and metrics["question_accuracy"] is None
    assert metrics["provenance"]["authority"] == "software_fixture"
    manifest = read_json(output / "run-manifest.json")
    assert manifest["max_generation_posts"] == manifest["max_posts_per_case"] == 4
    assert manifest["pipeline"] == "qwen-apertus"
    verify_directory(output)
    replay = score_evaluation(output, tmp_path / "offline-score")
    assert replay["technical_completions"] == 1 and replay["question_accuracy"] is None
    verify_directory(output)
