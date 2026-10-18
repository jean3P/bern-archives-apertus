"""Focused software checks only; no real HTTP or reference answers."""

from copy import deepcopy
import hashlib
import json

import httpx
import pytest

from core.answering import ANSWER_SCHEMA, run_answer
from core import answer_qualifications as aq
from core.config import Settings
from core.evaluation_scoring import inspect_case
from core.policy import SCHEMA_VERSION, SQL_SHA256
from core.search import build_index

TEXT = "The fee is seven tokens per term. Actual payment is irregular."
RECORD = {"record_id": "stapfer:answer:901", "answer_id": 901, "transcription_id": 101,
    "question_id": 1, "question_number": "I.1", "text_original": TEXT, "text_search": TEXT,
    "archive_reference": "SYNTHETIC", "pdf_page_index": None, "school_ids": [],
    "school_assignment_source_raw": None, "quality_flags": []}


def proposed():
    return {"status": "answered", "claims": [{"text": "Seven tokens per term. Actual payment is irregular.",
        "citations": [{"record_id": RECORD["record_id"], "quote": TEXT}]}],
        "message": ""}


def included():
    return {RECORD["record_id"]: {"record": RECORD, "delivered_passage": TEXT}}


def test_original_fields_separate_answered_claims_from_abstention_message():
    normalized = aq.normalize(proposed(), included())
    assert normalized["claims"][0]["text"] == "Seven tokens per term. Actual payment is irregular."
    assert normalized["message"] == proposed()["message"]
    schema = aq.answer_schema(ANSWER_SCHEMA)
    assert schema["anyOf"][0]["properties"]["message"]["enum"] == [""]
    assert schema["anyOf"][1]["properties"]["claims"]["maxItems"] == 0
    assert schema["anyOf"][1]["properties"]["message"]["minLength"] == 1
    assert "qualifications" not in ANSWER_SCHEMA["properties"]["claims"]["items"]["required"]


def test_v6_replay_keeps_its_message_but_new_decoder_contract_rejects_answer_in_message():
    value = proposed()
    value["message"] = "Additional uncited answer detail."
    assert aq.normalize(value, included(), aq.ORIGINAL_VERSION) == value
    with pytest.raises(ValueError, match="cited claims"):
        aq.normalize(value, included())
    with pytest.raises(ValueError, match="cited claims"):
        aq.normalize(value, included(), aq.CONCISE_VERSION)
    assert aq.normalize(proposed(), included(), aq.CONCISE_VERSION) == proposed()
    assert aq.answer_schema(ANSWER_SCHEMA, aq.CONCISE_VERSION) == aq.answer_schema(ANSWER_SCHEMA)


def test_saved_v5_replies_keep_their_original_offline_normalization():
    legacy = proposed()
    legacy["claims"][0].update(text="Seven tokens per term.", qualifications="Actual payment is irregular.")
    assert aq.normalize(legacy, included(), aq.LEGACY_VERSION) == proposed()
    with pytest.raises(ValueError):
        aq.normalize(legacy, included())


@pytest.mark.parametrize("mutation", ["quote", "id", "length"])
def test_original_citation_and_length_guards_remain(mutation):
    value = proposed()
    if mutation == "quote":
        value["claims"][0]["citations"][0]["quote"] = "Altered source text"
    elif mutation == "id":
        value["claims"][0]["citations"][0]["record_id"] = "stapfer:answer:999"
    else:
        value["claims"][0]["text"] = "x" * 601
    with pytest.raises(ValueError):
        aq.normalize(value, included())


def test_abstention_keeps_its_limitation_and_cannot_carry_positive_claims():
    value = {"status": "insufficient_evidence", "claims": [], "message": "The mapping is not verified."}
    assert aq.normalize(value, included()) == value
    value["claims"] = proposed()["claims"]
    with pytest.raises(ValueError):
        aq.normalize(value, included())


def test_existing_router_single_answer_retry_and_offline_receipt_replay(tmp_path, monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Real network is forbidden")
    monkeypatch.setattr("httpx.HTTPTransport.handle_request", denied)
    monkeypatch.setattr("core.answering.settings", lambda: Settings())
    directory = tmp_path / "data"
    directory.mkdir()
    catalogue = [{"question_id": 1, "question_number": "I.1", "text_original": "Fees", "text_french": None}]
    build_index(directory / "search.sqlite3", {"documents": [{"transcription_id": 101}],
        "questions": catalogue, "answers": [RECORD], "schools": [], "places": [], "teachers": [],
        "school_teachers": []}, SQL_SHA256)
    (directory / "source_manifest.json").write_text(json.dumps({"source_sha256": SQL_SHA256,
        "schema_version": SCHEMA_VERSION}), encoding="utf-8")
    (directory / "_SUCCESS.json").write_text(json.dumps({"status": "completed", "source_sha256": SQL_SHA256,
        "artifact_sha256": {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                            for name in ("source_manifest.json", "search.sqlite3")}}), encoding="utf-8")
    bad = deepcopy(proposed())
    bad["claims"][0]["citations"][0]["quote"] = "Wrong quotation"
    replies = iter([{"question_codes": ["I.1"]}, bad, proposed()])
    requests = []
    def wire(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": aq.MODEL}]})
        payload = json.loads(request.content)
        requests.append(payload)
        return httpx.Response(200, json={"model": aq.MODEL,
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(next(replies))}}]})
    question = "What fee and payment conditions are reported?"
    result, run = run_answer(question, 101, data_dir=directory, out=tmp_path / "run",
        pipeline="apertus-qualified", transport=httpx.MockTransport(wire))
    assert result["status"] == "answered" and "Actual payment is irregular." in result["answer"]
    assert [body["max_tokens"] for body in requests] == [180, 512, 512]
    from core.answering import retrieval_instructions
    assert requests[0]["messages"][0]["content"] == retrieval_instructions(scoped=True) + aq.ROUTING_INSTRUCTIONS
    assert requests[1]["messages"][0]["content"] == aq.INSTRUCTIONS
    implementation = json.loads((run / "implementation.json").read_text(encoding="utf-8"))
    assert implementation["retrieval_instructions_sha256"]["scoped"] == hashlib.sha256(
        requests[0]["messages"][0]["content"].encode()).hexdigest()
    assert not (run / "question_interpretation.json").exists()
    case = {"case_id": "SOFTWARE", "topic": "synthetic", "input": {"question": question,
        "transcription_id": 101}, "expected_status": "answered", "evidence": [{"answer_id": 901, "quote": TEXT}]}
    record = inspect_case(case, run, {"attempted": True, "response": result}, {"alternatives": []},
                          "software_fixture", pipeline="apertus-qualified")
    assert record["protocol_valid"] and record["mechanical_citation_valid"]
    assert record["generation_posts_attempted"] == 3 and record["format_retries"] == 1
