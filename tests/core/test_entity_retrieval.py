"""Small synthetic controls for entity scope and related evidence; no real HTTP."""
from copy import deepcopy
import hashlib
import json

import httpx
import pytest

from core import entity_retrieval as er
from core.answering import run_answer
from core.config import Settings
from core.evaluation_scoring import inspect_case
from core.evidence import EvidenceStore
from core.policy import SQL_SHA256
from core.search import build_index

CATALOGUE = [{"question_id": i, "question_number": code, "text_original": text,
              "text_french": None} for i, (code, text) in enumerate([
    ("I.1", "Place name"), ("I.1.a", "Place type"), ("I.1.d", "District"),
    ("III.11.b", "Teacher name"), ("III.11.d", "Teacher age"),
    ("III.11.e", "Teacher family"), ("IV.14", "Fees"), ("I.4.a", "Nearby schools")], 1)]


def record(identity, transcription, code, text):
    return {"record_id": f"stapfer:answer:{identity}", "answer_id": identity,
        "transcription_id": transcription, "question_id": next(row["question_id"] for row in CATALOGUE
                                                                if row["question_number"] == code),
        "question_number": code, "text_original": text, "text_search": text,
        "archive_reference": "SYNTHETIC", "pdf_page_index": None,
        "school_ids": [201, 202], "school_assignment_source_raw": 7,
        "quality_flags": ["school_links_are_transcription_context_not_answer_attribution",
                          "uninterpreted_school_assignment"]}


def records():
    return [record(901, 101, "I.1", "The school place is Testville."),
        record(902, 101, "I.1.d", "District Foxtrot."),
        record(903, 101, "III.11.b", "Ada Example."),
        record(904, 101, "III.11.d", "Thirty-nine years."),
        record(905, 101, "III.11.e", "Three family children."),
        record(906, 101, "IV.14", "$ none $$"),
        record(907, 102, "I.1", "Anotherplace."),
        record(908, 102, "I.1.d", "District Wrongscope."),
        record(909, 102, "I.4.a", "The nearby school is Testville.")]


def make_data(tmp_path, rows=None):
    directory = tmp_path / "data"
    directory.mkdir()
    build_index(directory / "search.sqlite3", {"documents": [{"transcription_id": 101},
        {"transcription_id": 102}], "questions": CATALOGUE, "answers": rows or records(),
        "schools": [], "places": [], "teachers": [], "school_teachers": []}, SQL_SHA256)
    (directory / "source_manifest.json").write_text(json.dumps({"test_fixture": True}))
    hashes = {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
              for name in ("source_manifest.json", "search.sqlite3")}
    (directory / "_SUCCESS.json").write_text(json.dumps({"status": "completed",
        "source_sha256": SQL_SHA256, "artifact_sha256": hashes}))
    return directory


def plan(*, name="Testville", kind="place", codes=None):
    return {"entities": [{"text": name, "kind": kind}], "question_codes": codes or ["I.1.d"]}


def select(directory, proposed):
    store = EvidenceStore(directory)
    try:
        return er.select_related(proposed, store, CATALOGUE)
    finally:
        store.close()


def test_related_district_is_retrieved_without_requiring_place_name_in_district_text(tmp_path):
    cards, reason, receipt = select(make_data(tmp_path), plan())
    assert reason is None and receipt["selected_transcription_id"] == 101
    assert [card["record_id"] for card in cards] == ["stapfer:answer:901", "stapfer:answer:902"]
    assert all(card["transcription_id"] == 101 for card in cards)
    assert all(card["record_id"] != "stapfer:answer:909" for card in cards)  # Neighbour is not owner.
    assert receipt["all_identity_and_requested_records_delivered"]
    assert cards[0]["text_original"] == records()[0]["text_original"]


def test_two_anchor_intersection_keeps_identity_and_both_requested_attributes(tmp_path):
    proposed = plan(codes=["III.11.d", "III.11.e"])
    proposed["entities"].append({"kind": "person", "text": "Ada Example"})
    cards, reason, receipt = select(make_data(tmp_path), proposed)
    assert not reason and len(cards) == 4
    assert {row["question_number"] for row in cards} == {"I.1", "III.11.b", "III.11.d", "III.11.e"}
    assert receipt["selected_transcription_id"] == 101


@pytest.mark.parametrize("mode", ["ambiguous", "missing", "conflicting", "no_entity"])
def test_uncertain_scope_is_held_instead_of_selecting_first_or_generic_dossier(tmp_path, mode):
    rows, proposed = records(), plan()
    if mode == "ambiguous":
        rows.append(record(910, 102, "I.1", "Testville."))
    elif mode == "missing":
        proposed["entities"][0]["text"] = "Missingville"
    elif mode == "conflicting":
        proposed["entities"].append({"kind": "place", "text": "Anotherplace"})
    else:
        proposed["entities"] = []
    cards, reason, receipt = select(make_data(tmp_path, rows), proposed)
    assert not cards and reason and receipt["status"] == "held"
    assert receipt["entity_witnesses"] is not None


@pytest.mark.parametrize("mode", ["null", "truncated"])
def test_missing_or_incomplete_requested_evidence_is_preserved_but_not_answered(tmp_path, mode):
    rows = records()
    rows[1]["text_original"] = rows[1]["text_search"] = None if mode == "null" else "x" * 2100
    cards, reason, receipt = select(make_data(tmp_path, rows), plan())
    assert not cards and reason and receipt["status"] == "held"
    assert receipt["related_records"][0]["text_original"] == rows[1]["text_original"]


def test_entity_plan_preserves_question_names_and_rejects_guessed_ids_and_codes():
    assert er.validate_plan(plan(), "Which district contains testville?", CATALOGUE)
    assert er.contains("$ à École-X $$", "école-x")
    for value in [plan(name="Inventedville"), plan(codes=["made.up"]),
                  {**plan(), "transcription_id": 101}]:
        with pytest.raises(ValueError):
            er.validate_plan(value, "Which district contains Testville?", CATALOGUE)


def test_live_interface_uses_same_answer_prompt_and_one_shared_answer_retry(tmp_path):
    directory = make_data(tmp_path)
    good = {"status": "answered", "message": "", "claims": [{"text": "The district is Foxtrot.",
        "citations": [{"record_id": "stapfer:answer:902", "quote": "District Foxtrot."}]}]}
    bad = deepcopy(good)
    bad["claims"][0]["citations"][0]["quote"] = "Not an original quote"
    replies, requests = iter([plan(), bad, good]), []
    def wire(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": Settings().model}]})
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(200, json={"model": Settings().model, "choices": [{
            "finish_reason": "stop", "message": {"content": json.dumps(next(replies))}}]})
    question = "Which district contains Testville?"
    result, out = run_answer(question, data_dir=directory, out=tmp_path / "run",
        config=Settings(), pipeline="apertus-qualified", retrieval_mode="entity",
        transport=httpx.MockTransport(wire))
    assert result["status"] == "answered" and "Foxtrot" in result["answer"]
    assert "unresolved" in result["message"]  # Multiple-school attribution warning survives.
    assert [body["max_tokens"] for body in requests] == [180, 512, 512]
    from core.answer_qualifications import INSTRUCTIONS
    assert requests[1]["messages"][0]["content"] == INSTRUCTIONS
    case = {"case_id": "SOFTWARE", "topic": "synthetic", "input": {"question": question,
        "transcription_id": None}, "expected_status": "answered",
        "evidence": [{"answer_id": 902, "quote": "District Foxtrot."}]}
    inspected = inspect_case(case, out, {"attempted": True, "response": result},
        {"alternatives": []}, "software_fixture", pipeline="apertus-qualified")
    assert inspected["protocol_valid"] and inspected["mechanical_citation_valid"]
    assert inspected["format_retries"] == 1 and inspected["generation_posts_attempted"] == 3


def test_explicit_scoped_request_and_unscoped_scope_hold_keep_original_behavior(tmp_path):
    directory = make_data(tmp_path)
    def denied(request):
        raise AssertionError("Unscoped explicit question must not call a model")
    result, out = run_answer("According to I.1.d, which district?", data_dir=directory,
        out=tmp_path / "unscoped", config=Settings(), pipeline="apertus-qualified",
        retrieval_mode="entity", transport=httpx.MockTransport(denied))
    assert result["status"] == "insufficient_evidence" and "Choose a transcription" in result["message"]
    assert json.loads((out / "summary.json").read_text())["generation_posts_attempted"] == 0
    assert json.loads((out / "entity_selection.json").read_text())["status"] == "standard_scope"
