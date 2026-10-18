"""Small targeted contract checks; mock generations only, not model accuracy."""

from copy import deepcopy
import hashlib
import json

import httpx
import pytest

from core import facet_answering as fa
from core.answering import run_answer
from core.config import ROOT, Settings
from core.evidence import make_packet
from core.evaluation import run_evaluation
from core.evaluation_scoring import inspect_case
from core.policy import SCHEMA_VERSION, SQL_SHA256
from core.search import build_index

CATALOGUE = [{"question_id": 1, "question_number": "I.1", "text_original": "Keeper family", "text_french": None},
             {"question_id": 2, "question_number": "I.2", "text_original": "School pupils", "text_french": None}]
TEXT = "Keeper aged thirty-one. Two family children. Payment prescribed but irregular."
RECORD = {"record_id": "stapfer:answer:901", "answer_id": 901, "transcription_id": 101,
    "question_id": 1, "question_number": "I.1", "text_original": TEXT, "text_search": TEXT,
    "archive_reference": "SYNTHETIC", "pdf_page_index": None, "school_ids": [],
    "school_assignment_source_raw": None, "quality_flags": []}


def plan():
    return {"question_codes": ["I.1"], "queries": [], "ambiguity": None, "facets": [
        {"subject": "keeper", "request": "age", "question_codes": ["I.1"]},
        {"subject": "keeper family", "request": "family count", "question_codes": ["I.1"]}]}


def test_interpretation_binds_requested_spans_and_literal_routes():
    fa.validate_interpretation(plan(), CATALOGUE, True, ["I.1"], "Give keeper age and family count")
    schema = fa.interpretation_schema(CATALOGUE, True, ["I.1"])
    assert schema["properties"]["question_codes"]["items"]["enum"] == ["I.1"]
    assert schema["properties"]["ambiguity"]["anyOf"][0] == {"type": "null"}
    wrong = plan()
    wrong["facets"][0]["request"] = "Find the catalogue code for age"
    with pytest.raises(ValueError, match="verbatim"):
        fa.validate_interpretation(wrong, CATALOGUE, True, ["I.1"], "Give keeper age and family count")
    wrong = plan()
    wrong["question_codes"].append("I.2")
    wrong["facets"][1]["question_codes"].append("I.2")
    with pytest.raises(ValueError, match="exactly"):
        fa.validate_interpretation(wrong, CATALOGUE, True, ["I.1"], "Give keeper age and family count")


def parts():
    return {"parts": [{"facet_id": "f1", "status": "answered", "answer": "The keeper is thirty-one.",
        "qualifications": [], "citations": [{"record_id": RECORD["record_id"], "quote": TEXT}], "message": ""},
        {"facet_id": "f2", "status": "answered", "answer": "The keeper has two family children.",
        "qualifications": [], "citations": [{"record_id": RECORD["record_id"], "quote": TEXT}], "message": ""}]}


def included():
    return make_packet([RECORD], CATALOGUE)[1]


@pytest.mark.parametrize("change", ["omission", "duplicate_id", "wrong_quote"])
def test_omission_wrong_binding_and_invalid_quote_are_rejected(change):
    value = parts()
    if change == "omission":
        value["parts"].pop()
    elif change == "duplicate_id":
        value["parts"][1]["facet_id"] = "f1"
    else:
        value["parts"][0]["citations"][0]["quote"] = "Invented quotation"
    with pytest.raises(ValueError):
        fa.validate_parts(value, plan(), included())


def test_qualifications_become_visible_answer_text_without_source_replacement():
    value = parts()
    value["parts"][0].update(answer="Payment is prescribed.", qualifications=["Actual payment is irregular."])
    result = fa.validate_parts(value, plan(), included())
    assert result["claims"][0]["text"] == "Payment is prescribed. Actual payment is irregular."
    assert result["claims"][0]["citations"][0]["quote"] == TEXT


def test_unresolved_part_or_material_ambiguity_cannot_become_a_positive_answer():
    value = parts()
    value["parts"][1].update(status="insufficient_evidence", answer="", citations=[], message="Family count unclear.")
    result = fa.validate_parts(value, plan(), included())
    assert result["status"] == "insufficient_evidence" and not result["claims"]
    ambiguous = plan()
    ambiguous["ambiguity"] = "The intended population is unclear."
    with pytest.raises(ValueError, match="ambiguity"):
        fa.validate_parts(parts(), ambiguous, included())


def test_wrong_survey_population_citation_is_rejected():
    pupil = {**RECORD, "record_id": "stapfer:answer:902", "answer_id": 902,
             "question_id": 2, "question_number": "I.2", "text_original": "Twenty pupils."}
    delivered = make_packet([RECORD, pupil], CATALOGUE)[1]
    value = parts()
    value["parts"][1]["citations"] = [{"record_id": pupil["record_id"], "quote": pupil["text_original"]}]
    with pytest.raises(ValueError, match="different subject"):
        fa.validate_parts(value, plan(), delivered)


def test_well_shaped_wrong_meaning_still_needs_semantic_review():
    value = parts()
    value["parts"][1]["answer"] = "The keeper has fifty children."
    assert fa.validate_parts(value, plan(), included())["claims"][1]["text"] == "The keeper has fifty children."


@pytest.fixture
def dataset(tmp_path, monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Real network is forbidden in software checks")
    monkeypatch.setattr("httpx.HTTPTransport.handle_request", denied)
    monkeypatch.setattr("core.answering.settings", lambda: Settings())
    directory = tmp_path / "dataset"
    directory.mkdir()
    build_index(directory / "search.sqlite3", {"documents": [{"transcription_id": 101}], "questions": CATALOGUE,
        "answers": [RECORD], "schools": [], "places": [], "teachers": [], "school_teachers": []}, SQL_SHA256)
    (directory / "source_manifest.json").write_text(json.dumps({"source_sha256": SQL_SHA256,
        "schema_version": SCHEMA_VERSION}), encoding="utf-8")
    (directory / "_SUCCESS.json").write_text(json.dumps({"status": "completed", "source_sha256": SQL_SHA256,
        "artifact_sha256": {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                            for name in ("source_manifest.json", "search.sqlite3")}}), encoding="utf-8")
    return directory


def acquire(dataset, destination, replies):
    requests, replies = [], iter(replies)
    def wire(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": fa.MODEL}]})
        payload = json.loads(request.content)
        assert payload["model"] == fa.MODEL
        requests.append(payload)
        return httpx.Response(200, json={"model": fa.MODEL,
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(next(replies))}}]})
    response, directory = run_answer("Give keeper age and family count", 101,
        data_dir=dataset, out=destination, pipeline="apertus-facets", transport=httpx.MockTransport(wire))
    return response, directory, requests


def test_one_retry_keeps_three_call_budget_and_replays_offline(dataset, tmp_path):
    incomplete = parts()
    incomplete["parts"].pop()
    response, directory, requests = acquire(dataset, tmp_path / "run", [plan(), incomplete, parts()])
    assert response["status"] == "answered" and len(requests) == 3
    assert [row["max_tokens"] for row in requests] == [512, 1024, 1024]
    assert not (directory / "qwen-serving.json").exists()
    case = {"case_id": "SOFTWARE", "topic": "synthetic", "input": {"question": "Give keeper age and family count",
        "transcription_id": 101}, "expected_status": "answered", "evidence": [{"answer_id": 901, "quote": TEXT}]}
    inspected = inspect_case(case, directory, {"attempted": True, "response": response},
        {"alternatives": []}, "software_fixture", pipeline="apertus-facets")
    assert inspected["protocol_valid"] and inspected["mechanical_citation_valid"]
    assert inspected["format_retries"] == 1 and inspected["generation_posts_attempted"] == 3


def test_interpretation_retry_spends_the_same_answer_allowance(dataset, tmp_path):
    invalid = plan()
    invalid["question_codes"] = ["I.99"]
    incomplete = parts()
    incomplete["parts"].pop()
    response, directory, requests = acquire(dataset, tmp_path / "spent", [invalid, plan(), incomplete])
    assert response["status"] == "error" and len(requests) == 3
    assert json.loads((directory / "summary.json").read_text())["format_retries"] == 1


def test_unavailable_service_fails_before_any_evaluation_question(dataset, tmp_path, monkeypatch):
    class Unavailable:
        def __init__(self, config):
            pass
        def models(self):
            raise httpx.ConnectError("Synthetic unavailable endpoint")
        def close(self):
            pass
    monkeypatch.setattr("core.apertus.ApertusClient", Unavailable)
    monkeypatch.setattr("core.config.settings", lambda: Settings())
    monkeypatch.setattr("core.dataset_cli.verify", lambda _: {"status": "verified"})
    output = tmp_path / "blocked-batch"
    with pytest.raises(ValueError, match="batch was not started"):
        run_evaluation(ROOT / "evaluation/references/draft-v1", "development", dataset,
                       output, allow_draft=True, pipeline="apertus-facets")
    assert (output / "_FAILED.json").is_file() and not (output / "cases").exists()
