"""Bounded synthetic coverage controls, not historical question accuracy."""
from copy import deepcopy
import json

import httpx
import pytest

from core import answer_coverage as ac
from core.answering import run_answer
from core.config import Settings
from core.evaluation_scoring import inspect_case
from core.evidence import EvidenceStore, make_packet
from test_entity_retrieval import CATALOGUE, make_data, records


def plan():
    return {"entities": [], "requirements": [
        {"label": "Age", "question_codes": ["III.11.d"], "answer_type": "fact"},
        {"label": "Family", "question_codes": ["III.11.e"], "answer_type": "fact"}]}


def selected():
    packet, included, _ = make_packet(records()[3:5], CATALOGUE)
    return ac.span_bank(packet), included


def answer():
    return {"status": "answered", "message": "", "claims": [
        {"text": "Thirty-nine years.", "citations": [{"span_id": "s1"}]},
        {"text": "Three family children.", "citations": [{"span_id": "s2"}]}]}


def test_software_copies_original_quote_and_cannot_accept_generated_quote():
    spans, included = selected()
    value = ac.normalize(answer(), plan(), spans, included)
    assert value["claims"][1]["citations"][0]["quote"] == "Three family children."
    mutated = deepcopy(spans)
    mutated[1]["quote"] = "Three\u202ffamily children."
    with pytest.raises(ValueError, match="exact span"):
        ac.normalize(answer(), plan(), mutated, included)


@pytest.mark.parametrize("mutation", ["empty", "extra_field", "unknown_span", "unsupported_citation", "hidden_qualifier", "echo"])
def test_invalid_or_question_echo_outputs_rejected(mutation):
    spans, included = selected()
    raw = answer()
    if mutation == "empty":
        raw["claims"] = []
    elif mutation == "extra_field":
        raw["claims"][0]["unexpected"] = True
    elif mutation == "unknown_span":
        raw["claims"][1]["citations"] = [{"span_id": "not_delivered"}]
    elif mutation == "unsupported_citation":
        raw["status"] = "insufficient_evidence"
        raw["message"] = "Missing detail"
    elif mutation == "hidden_qualifier":
        raw["message"] = "Qualification outside answer"
    else:
        raw["claims"][0]["text"] = plan()["requirements"][0]["label"]
    with pytest.raises(ValueError):
        ac.normalize(raw, plan(), spans, included)


def test_one_missing_required_attribute_abstains_without_erasing_raw_supported_rows():
    spans, included = selected()
    raw = answer()
    raw = {"status": "insufficient_evidence", "claims": [], "message": "Family detail is unsupported."}
    value = ac.normalize(raw, plan(), spans, included)
    assert value["status"] == "insufficient_evidence" and not value["claims"]
    assert value["message"] == "Family detail is unsupported."


def test_explicit_scope_cannot_be_expanded_to_find_an_unrequested_attribute():
    with pytest.raises(ValueError, match="scope"):
        ac.validate_plan(plan(), "According to III.11.d, what is the age?", CATALOGUE)


def test_controller_receipts_exact_translation_and_single_shared_retry(tmp_path):
    data = make_data(tmp_path)
    raw = {"status": "answered", "message": "", "claims": [
        {"text": "Three family children.", "citations": [{"span_id": "s1"}]}]}
    bad = deepcopy(raw)
    bad["claims"][0]["citations"] = []
    replies, requests = iter([{"r1": []}, bad, raw]), []
    def wire(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": Settings().model}]})
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(200, json={"model": Settings().model, "choices": [{
            "finish_reason": "stop", "message": {"content": json.dumps(next(replies))}}]})
    question = "How many children does the teacher have?"
    response, out = run_answer(question, 101, data_dir=data, out=tmp_path / "run", config=Settings(),
        pipeline="apertus-qualified", retrieval_mode="coverage", transport=httpx.MockTransport(wire))
    assert response["status"] == "answered" and "Three family" in response["answer"]
    assert [body["max_tokens"] for body in requests] == [ac.PLAN_TOKENS, ac.ANSWER_TOKENS, ac.ANSWER_TOKENS]
    assert json.loads((out / "coverage_answer.json").read_text())["parts"][0]["raw"] == raw
    assert json.loads((out / "coverage_related_fields.json").read_text())["added_catalogue_codes"] == ["III.11.e"]
    assert json.loads((out / "coverage_route.json").read_text())["r1"] == []
    case = {"case_id": "SYNTHETIC", "topic": "synthetic", "input": {"question": question,
        "transcription_id": 101}, "expected_status": "answered", "evidence": [{"answer_id": 905,
        "quote": "Three family children."}]}
    result = inspect_case(case, out, {"attempted": True, "response": response},
        {"alternatives": []}, "software_fixture", pipeline="apertus-qualified")
    assert result["protocol_valid"] and result["mechanical_citation_valid"]
    assert result["format_retries"] == 1


def test_original_markup_is_retained_byte_for_byte():
    spans, included = selected()
    original = "¦ one @ two ¦¦ three\u00a0four"
    spans[0]["quote"] = included["stapfer:answer:904"]["delivered_passage"] = original
    value = ac.normalize(answer(), plan(), spans, included)
    assert value["claims"][0]["citations"][0]["quote"] == original


def test_literal_units_do_not_invent_tasks_and_preserve_exact_date_format():
    units = ac.literal_requirements("According to IV.14, what fees for day pupils, evening pupils and night pupils? Preserve periods.")
    assert [u["label"] for u in units] == ["what fees for day pupils", "evening pupils", "night pupils?"]
    assert len(ac.literal_requirements("Using only III.11.d, what is the exact date of birth, including day, month and year?")) == 1
    assert len(ac.literal_requirements("Quel âge a le maître et quels âges ont ses fils ?")) == 2
    assert len(ac.literal_requirements("According to II.5, which five skills precede the memorisation list?")) == 1


def test_teacher_family_field_is_not_confused_with_fathers_financing_the_school():
    catalogue = deepcopy(CATALOGUE) + [
        {"question_number": "III.11", "text_original": "Schullehrer.", "text_french": "Instituteurs."},
        {"question_number": "IV.16.B.f", "text_original": "Zusammengelegte Gelder",
         "text_french": "Argent des pères de famille."}]
    assert ac.teacher_family_fields(catalogue) == ["III.11.e"]


def test_exact_calendar_date_gate_does_not_turn_age_into_birthdate():
    proposed = {"requirements": [{"answer_type": "exact_date"}]}
    assert ac.date_type_hold(proposed, [{"passage": "The teacher is 39 years old."}])
    for text in ["Born 12 June 1760.", "Geboren 12. März 1760.", "Né le 12 juin 1760.", "12.06.1760"]:
        assert ac.date_type_hold(proposed, [{"passage": text}]) is None
    assert ac.date_type_hold({"requirements": [{"answer_type": "fact"}]}, [{"passage": "Age 39."}]) is None


def test_global_entity_request_is_frozen_and_receipts_replay(tmp_path):
    data = make_data(tmp_path)
    from core.entity_retrieval import INSTRUCTIONS
    replies = iter([{"entities": [], "question_codes": ["I.1.d"]},
        {"status": "answered", "message": "", "claims": [{
            "text": "The district is Foxtrot.", "citations": [{"span_id": "s2"}]}]}])
    requests = []
    def wire(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": Settings().model}]})
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(200, json={"model": Settings().model, "choices": [{
            "finish_reason": "stop", "message": {"content": json.dumps(next(replies))}}]})
    question = "Which district contains Testville?"
    response, out = run_answer(question, data_dir=data, out=tmp_path / "run", config=Settings(),
        pipeline="apertus-qualified", retrieval_mode="coverage", transport=httpx.MockTransport(wire))
    assert response["status"] == "answered" and requests[0]["messages"][0]["content"] == INSTRUCTIONS
    case = {"case_id": "SYNTHETIC", "topic": "synthetic", "input": {"question": question,
        "transcription_id": None}, "expected_status": "answered", "evidence": [{"answer_id": 902,
        "quote": "District Foxtrot."}]}
    inspected = inspect_case(case, out, {"attempted": True, "response": response},
        {"alternatives": []}, "software_fixture", pipeline="apertus-qualified")
    assert inspected["protocol_valid"] and inspected["mechanical_citation_valid"]
