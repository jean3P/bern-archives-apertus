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
    return {"r1": {"supported": True, "answer": "Thirty-nine years.", "spans": ["s1"], "reason": ""},
            "r2": {"supported": True, "answer": "Three family children.", "spans": ["s2"], "reason": ""}}


def test_software_copies_original_quote_and_cannot_accept_generated_quote():
    spans, included = selected()
    value = ac.normalize(answer(), plan(), spans, included)
    assert value["claims"][1]["citations"][0]["quote"] == "Three family children."
    mutated = deepcopy(spans)
    mutated[1]["quote"] = "Three\u202ffamily children."
    with pytest.raises(ValueError, match="exact span"):
        ac.normalize(answer(), plan(), mutated, included)


@pytest.mark.parametrize("mutation", ["missing", "extra", "unknown_span", "unsupported_citation", "hidden_qualifier"])
def test_incomplete_or_invalid_per_detail_outputs_rejected(mutation):
    spans, included = selected()
    raw = answer()
    if mutation == "missing":
        del raw["r2"]
    elif mutation == "extra":
        raw["r3"] = raw["r1"]
    elif mutation == "unknown_span":
        raw["r2"]["spans"] = ["not_delivered"]
    elif mutation == "unsupported_citation":
        raw["r2"].update(supported=False, reason="Missing detail")
    else:
        raw["r1"]["reason"] = "Qualification outside answer"
    with pytest.raises(ValueError):
        ac.normalize(raw, plan(), spans, included)


def test_one_missing_required_attribute_abstains_without_erasing_raw_supported_rows():
    spans, included = selected()
    raw = answer()
    raw["r2"] = {"supported": False, "answer": "", "spans": [], "reason": "Family detail is unsupported."}
    value = ac.normalize(raw, plan(), spans, included)
    assert value["status"] == "insufficient_evidence" and not value["claims"]
    assert raw["r1"]["answer"] == "Thirty-nine years."


def test_explicit_scope_cannot_be_expanded_to_find_an_unrequested_attribute():
    with pytest.raises(ValueError, match="scope"):
        ac.validate_plan(plan(), "According to III.11.d, what is the age?", CATALOGUE)


def test_controller_receipts_exact_translation_and_single_shared_retry(tmp_path):
    data = make_data(tmp_path)
    raw = answer()
    bad = deepcopy(raw)
    bad["r2"]["spans"] = []
    replies, requests = iter([plan(), bad, raw]), []
    def wire(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": Settings().model}]})
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(200, json={"model": Settings().model, "choices": [{
            "finish_reason": "stop", "message": {"content": json.dumps(next(replies))}}]})
    question = "How old is the teacher and how many family children?"
    response, out = run_answer(question, 101, data_dir=data, out=tmp_path / "run", config=Settings(),
        pipeline="apertus-qualified", retrieval_mode="coverage", transport=httpx.MockTransport(wire))
    assert response["status"] == "answered" and "Three family" in response["answer"]
    assert [body["max_tokens"] for body in requests] == [ac.PLAN_TOKENS, ac.ANSWER_TOKENS, ac.ANSWER_TOKENS]
    assert json.loads((out / "coverage_answer.json").read_text()) == raw
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
