"""Synthetic binding and omission controls; no historical reference answers."""
from copy import deepcopy
import json

import httpx
import pytest

from core import answer_binding as ab
from core.answering import run_answer
from core.config import Settings
from core.evaluation_scoring import inspect_case
from core.evidence import make_packet
from test_entity_retrieval import CATALOGUE, make_data, records


def fixture():
    packet, included, _ = make_packet(records()[0:2], CATALOGUE)
    plan = {"scope": "supplied_transcription", "requirements": [
        {"label": "place", "question_codes": ["I.1"], "answer_type": "fact"},
        {"label": "district", "question_codes": ["I.1.d"], "answer_type": "fact"}]}
    binding = ab.bound_units(plan, packet)
    raw = {"status": "answered", "message": "", "answers": {
        "r1": {"text": "The place is Testville.", "citations": [{"span_id": "s1"}]},
        "r2": {"text": "The district is Foxtrot.", "citations": [{"span_id": "s2"}]}}}
    return packet, included, plan, binding, raw


def test_positive_field_binding_and_original_quote_translation():
    _, included, _, binding, raw = fixture()
    value = ab.normalize(raw, binding, included, ab.schedule_requirements("Which place and district?", binding))
    assert value["claims"][1]["citations"][0] == {
        "record_id": "stapfer:answer:902", "quote": "District Foxtrot."}
    assert binding["units"]["r2"]["citation_spans"][0]["survey_question"] == "District"
    assert binding["units"]["r2"]["citation_spans"][0]["passage_complete"] is True


@pytest.mark.parametrize("mutation", ["cross_field", "missing_detail", "extra_detail", "empty_quote", "hidden_answer", "echo"])
def test_bad_binding_and_incomplete_structure_are_rejected(mutation):
    _, included, _, binding, raw = fixture()
    if mutation == "cross_field":
        raw["answers"]["r2"]["citations"] = [{"span_id": "s1"}]
    elif mutation == "missing_detail":
        del raw["answers"]["r2"]
    elif mutation == "extra_detail":
        raw["answers"]["extra"] = raw["answers"]["r1"]
    elif mutation == "empty_quote":
        binding["units"]["r2"]["citation_spans"][0]["quote"] = "not the source"
    elif mutation == "hidden_answer":
        raw["message"] = "The actual answer was hidden here."
    else:
        raw["answers"]["r1"]["text"] = binding["units"]["r1"]["detail"]
    with pytest.raises(ValueError):
        ab.normalize(raw, binding, included, ab.schedule_requirements("What place?", binding))


def test_empty_binding_does_not_expand_to_every_source():
    packet, _, plan, _, _ = fixture()
    plan["requirements"][1]["question_codes"] = []
    binding = ab.bound_units(plan, packet)
    assert binding["unresolved"] == ["r2"] and binding["units"]["r2"]["citation_spans"] == []
    assert binding["units"]["r1"]["citation_spans"]


def test_shared_passage_has_separate_record_and_field_owners():
    packet, _, plan, _, _ = fixture()
    packet[0]["records"].append(packet[1]["records"][0])
    packet = packet[:1]
    binding = ab.bound_units(plan, packet)
    assert binding["units"]["r1"]["citation_spans"][0]["record_id"] == "stapfer:answer:901"
    assert binding["units"]["r2"]["citation_spans"][0]["record_id"] == "stapfer:answer:902"


@pytest.mark.parametrize("text", ["1 1/2. ß.", "1½ß", "1.5 ß", "1,5 ß"])
def test_numeric_analysis_handles_equivalent_notation_without_changing_quotes(text):
    assert ab.amount_atoms(text) == [["3/2", "ß"]]


def test_full_schedule_checks_actual_source_amounts_and_period_words():
    _, included, _, binding, raw = fixture()
    source = "Winter weekly 2 ß; summer 11 ß; whole year 13 ß."
    for key in binding["units"]:
        binding["units"][key]["citation_spans"][0]["quote"] = source
    for record in included.values():
        record["delivered_passage"] = source
    required = ab.schedule_requirements("List all fees and preserve periods.", binding)
    raw["answers"]["r1"]["text"] = "Winter weekly 2 ß, summer 11 ß."
    raw["answers"]["r2"]["text"] = "13 ß for the whole year."
    assert ab.normalize(raw, binding, included, required)["status"] == "answered"
    for bad in ("Winter weekly 2 ß and summer payment.", "Winter weekly 2 ß, summer 12 ß."):
        changed = deepcopy(raw)
        changed["answers"]["r1"]["text"] = bad
        with pytest.raises(ValueError, match="Incomplete schedule"):
            ab.normalize(changed, binding, included, required)
    changed = deepcopy(raw)
    changed["answers"]["r1"]["text"] = "Winter 2 ß, summer 11 ß."
    with pytest.raises(ValueError, match="weekly"):
        ab.normalize(changed, binding, included, required)
    assert not ab.schedule_requirements("Who pays the fee?", binding)["active"]
    assert required["not_population_pairing_or_entailment_verification"] is True


@pytest.mark.parametrize("pipeline,model", [("apertus-qualified", Settings().model),
    ("qwen-only", "Qwen/Qwen3-VL-32B-Instruct")])
@pytest.mark.parametrize("unresolved", [False, True])
def test_runtime_keeps_full_question_and_replays_receipts(tmp_path, pipeline, model, unresolved):
    data = make_data(tmp_path)
    question = "According to I.1 and I.1.d, what is the place and its district?"
    raw = fixture()[-1]
    replies = iter([{"r1": ["I.1"], "r2": [] if unresolved else ["I.1.d"]}, raw])
    requests = []
    def wire(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": model}]})
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(200, json={"model": model, "choices": [{
            "finish_reason": "stop", "message": {"content": json.dumps(next(replies))}}]})
    response, output = run_answer(question, 101, data_dir=data, out=tmp_path / "run",
        config=Settings(model=model), pipeline=pipeline, retrieval_mode="bound",
        transport=httpx.MockTransport(wire))
    assert response["status"] == ("insufficient_evidence" if unresolved else "answered")
    assert len(requests) == (1 if unresolved else 2)
    routed = json.loads(requests[0]["messages"][1]["content"])
    assert {row["question_number"] for group in routed["scoped_original_passages"]
            for row in group["records"]} == {"I.1", "I.1.d"}
    assert all(group["transcription_id"] == 101 for group in routed["scoped_original_passages"])
    if not unresolved:
        assert json.loads(requests[1]["messages"][1]["content"])["question"] == question
    case = {"case_id": "SYNTHETIC", "topic": "synthetic", "input": {
        "question": question, "transcription_id": 101}, "expected_status": "answered", "evidence": [
        {"answer_id": 901, "quote": "The school place is Testville."}]}
    inspected = inspect_case(case, output, {"attempted": True, "response": response},
        {"alternatives": []}, "software_fixture", pipeline=pipeline)
    assert inspected["protocol_valid"]


def test_genuine_nonanswer_does_not_require_fake_completeness():
    _, included, _, binding, _ = fixture()
    value = ab.normalize({"status": "insufficient_evidence", "answers": {},
        "message": "The required fact is not in the supplied evidence."}, binding, included,
        ab.schedule_requirements("What is the exact GPS?", binding))
    assert value["status"] == "insufficient_evidence"


def test_catalogue_scope_syntax_is_not_an_extra_answer_requirement():
    units = ab.question_units("What place and district are named in I.1 and I.1.d?", CATALOGUE)
    assert [unit["label"] for unit in units] == ["What place", "district are named?"]
    units = ab.question_units("For III.11.d, what is the verified zero-based PDF page index?", CATALOGUE)
    assert len(units) == 1 and units[0]["label"].startswith("what is the verified")
    assert len(ab.question_units("According to I.1 and I.1.d, what place and district?", CATALOGUE)) == 2


def test_pdf_index_requires_actual_metadata_not_age_or_editorial_marker():
    packet, _, _, _, _ = fixture()
    packet[0]["passage"] = "Age 39. ||[Seite 7]"
    question = "What is the verified zero-based PDF page index?"
    assert ab.metadata_hold(question, packet)["reason"] == "no_verified_pdf_page_index"
    assert ab.metadata_hold("How old is the teacher?", packet) is None
    packet[0]["records"][0]["pdf_page_index"] = 7
    assert ab.metadata_hold(question, packet) is None
