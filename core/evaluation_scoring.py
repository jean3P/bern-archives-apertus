"""Mechanical observations and explicitly reviewed scores; never calls a model."""

import math
from statistics import median

from contracts import validate_response
from core.evaluation_records import digest, read_json, read_jsonl, strict_loads, value_hash
from core.evidence import format_answer, validate_answer


def accepted_ids(case, reference, aliases):
    values = [reference["answer_id"]]
    for entry in aliases["alternatives"]:
        if entry["case_id"] == case["case_id"] and entry["base_answer_id"] == reference["answer_id"]:
            values = entry["accepted_answer_ids"]
    return {"stapfer:answer:" + str(value) for value in values}


def inspect_case(case, directory, observation, aliases, authority):
    try:
        return _inspect_case(case, directory, observation, aliases, authority)
    except (ValueError, TypeError, KeyError, OSError, AttributeError) as error:
        # A broken receipt is a failed observation, never an omitted question.
        return {"case_id": case["case_id"], "topic": case["topic"], "input": dict(case["input"]),
            "expected_status": case["expected_status"], "observed_status": "receipt_error",
            "attempted": observation["attempted"], "response": observation.get("response"),
            "reason": "receipt_inspection_" + type(error).__name__, "receipt_sha256": {},
            "protocol_valid": False, "response_contract_valid": False, "status_matches": False,
            "mechanical_citation_valid": None, "claim_count": 0, "reference_hit_at_5": None,
            "all_reference_spans_delivered": None, "packet_nonempty": None,
            "generation_posts_attempted": None, "generation_requests_in_log": 0,
            "format_retries": None, "total_seconds": None, "stage_timings": {}, "token_usage": {},
            "definitive_failure": True, "review_binding": value_hash({"case": case,
                "observation": observation, "inspection_error": type(error).__name__})}


def _inspect_case(case, directory, observation, aliases, authority):
    """Inspect existing receipts only. Semantic correctness always starts pending."""
    receipt_hashes = {path.name: digest(path) for path in sorted(directory.iterdir()) if path.is_file()} if directory.exists() else {}
    def saved(name, default):
        return read_json(directory / name) if name in receipt_hashes else default
    attempted = observation["attempted"]
    response = saved("response.json", observation.get("response"))
    summary = saved("summary.json", {})
    events = read_jsonl(directory / "events.jsonl") if "events.jsonl" in receipt_hashes else []
    requests = [event for event in events if event.get("event") == "generation_request"]
    calls, repairs = summary.get("generation_posts_attempted"), summary.get("format_retries")
    budget_valid = (not attempted or (type(calls) is int and 0 <= calls <= 3 and calls == len(requests)
        and type(repairs) is int and 0 <= repairs <= 1))
    if not attempted:
        calls, repairs = 0, 0
    request = saved("input.json", {})
    input_bound = (attempted and request.get("question") == case["input"]["question"]
                   and request.get("transcription_id") == case["input"]["transcription_id"])
    transport_bound = (not attempted or summary.get("transport") ==
                       ("actual_http" if authority == "actual_http" else "mock_transport"))
    contract_valid = False
    if response is not None:
        try:
            validate_response(response)
            contract_valid = response["mode"] == "live"
        except (ValueError, TypeError, KeyError):
            pass
    protocol_valid = bool(not attempted or (budget_valid and input_bound and transport_bound
        and "response.json" in receipt_hashes and "summary.json" in receipt_hashes
        and isinstance(response, dict) and observation.get("response") == response
        and summary.get("status") == response.get("status")))
    status = response.get("status", "error") if isinstance(response, dict) else "not_run"
    cards = saved("retrieved_sources.json", [])
    packet = saved("evidence.json", {}).get("packet", [])
    delivered = {}
    card_map = {card["record_id"]: card for card in cards}
    for group in packet:
        for member in group["records"]:
            record_id = member["record_id"]
            if record_id in card_map:
                delivered[record_id] = {"record": {**card_map[record_id], **member},
                                        "delivered_passage": group["passage"]}
    claims = saved("validated_claims.json", None)
    citation_valid = None
    if status == "answered":
        try:
            validate_answer(claims, delivered)
            citation_valid = claims["status"] == "answered" and format_answer(claims, delivered) == response
        except (ValueError, TypeError, KeyError, AttributeError):
            citation_valid = False
    if status == "insufficient_evidence" and packet:
        try:
            validate_answer(claims, delivered)
            contract_valid = contract_valid and claims["status"] == "insufficient_evidence" and format_answer(claims, delivered) == response
        except (ValueError, TypeError, KeyError):
            contract_valid = False
    claim_count = len(claims["claims"]) if isinstance(claims, dict) and status == "answered" and isinstance(claims.get("claims"), list) else 0
    if status == "insufficient_evidence":
        contract_valid = contract_valid and isinstance(response.get("message"), str) and bool(response["message"].strip())

    def matched(reference, selected):
        ids = accepted_ids(case, reference, aliases)
        return any(record_id in ids and reference["quote"] in passage for record_id, passage in selected)
    answerable = case["expected_status"] == "answered"
    top5 = [(card["record_id"], card["text_original"]) for card in cards[:5]]
    packet_spans = [(key, value["delivered_passage"]) for key, value in delivered.items()]
    hit = any(matched(ref, top5) for ref in case["evidence"]) if answerable and attempted else None
    coverage = all(matched(ref, packet_spans) for ref in case["evidence"]) if answerable and attempted else None
    timings = summary.get("timing_seconds", {})
    seconds = timings.get("total_seconds")
    if type(seconds) not in (float, int) or not math.isfinite(seconds) or seconds < 0:
        seconds = None
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "responses_with_usage": 0}
    for event in events:
        if event.get("event") != "generation_response":
            continue
        try:
            token_usage = strict_loads(event["body"]).get("usage", {})
            if all(type(token_usage.get(key)) is int and token_usage[key] >= 0 for key in ("prompt_tokens", "completion_tokens")):
                for key in ("prompt_tokens", "completion_tokens"):
                    usage[key] += token_usage[key]
                usage["responses_with_usage"] += 1
        except (ValueError, TypeError, KeyError, AttributeError):
            pass
    definitive_failure = (not attempted or not protocol_valid or not contract_valid
        or status != case["expected_status"] or (status == "answered" and citation_valid is not True))
    return {"case_id": case["case_id"], "topic": case["topic"], "input": dict(case["input"]),
        "expected_status": case["expected_status"], "observed_status": status,
        "attempted": attempted, "response": response, "reason": observation.get("reason"),
        "receipt_sha256": receipt_hashes, "protocol_valid": protocol_valid,
        "response_contract_valid": contract_valid, "status_matches": status == case["expected_status"],
        "mechanical_citation_valid": citation_valid, "claim_count": claim_count,
        "reference_hit_at_5": hit, "all_reference_spans_delivered": coverage,
        "packet_nonempty": bool(packet) if attempted else None,
        "generation_posts_attempted": calls if budget_valid else None,
        "generation_requests_in_log": len(requests), "format_retries": repairs if budget_valid else None,
        "total_seconds": seconds, "stage_timings": timings, "token_usage": usage,
        "definitive_failure": definitive_failure,
        "review_binding": value_hash({"case": case, "receipts": receipt_hashes,
                                     "response": response, "attempted": attempted})}


def review_template(records):
    return [{"case_id": row["case_id"], "review_binding": row["review_binding"],
             "reviewer": None, "decision": None, "supported_claims": None, "notes": ""} for row in records]


def load_reviews(path, records):
    if path is None:
        return {}
    by_id = {record["case_id"]: record for record in records}
    reviews = {}
    for review in read_jsonl(path):
        if set(review) != {"case_id", "review_binding", "reviewer", "decision", "supported_claims", "notes"}:
            raise ValueError("Unexpected review fields; keep the template structure")
        case_id = review["case_id"]
        if case_id not in by_id or case_id in reviews:
            raise ValueError("Unknown or repeated reviewed case")
        record = by_id[case_id]
        if review["review_binding"] != record["review_binding"]:
            raise ValueError("Review belongs to a different case or response")
        decision, supported = review["decision"], review["supported_claims"]
        if decision not in (None, "correct", "incorrect", "uncertain") or not isinstance(review["notes"], str):
            raise ValueError("Invalid semantic review decision")
        if decision is not None and (not isinstance(review["reviewer"], str) or not review["reviewer"].strip()):
            raise ValueError("A semantic decision needs a named reviewer")
        if supported is not None and (type(supported) is not int or not 0 <= supported <= record["claim_count"]):
            raise ValueError("Invalid supported-claim count")
        if decision is None and supported is not None:
            raise ValueError("Claim support needs an explicit review decision")
        if decision == "correct" and (record["definitive_failure"] or
                (record["observed_status"] == "answered" and supported != record["claim_count"])):
            raise ValueError("Review cannot pass a failed response or leave its claim support unchecked")
        reviews[case_id] = review
    return reviews


def apply_reviews(records, reviews):
    result = []
    for record in records:
        review = reviews.get(record["case_id"], {})
        decision = review.get("decision")
        correct = False if record["definitive_failure"] else (
            True if decision == "correct" else False if decision == "incorrect" else None)
        result.append({**record, "semantic_review": review or None, "final_correct": correct})
    return result


def aggregate(records):
    def ratio(numerator, denominator):
        return numerator / denominator if denominator else None
    total = len(records)
    answerable = [row for row in records if row["expected_status"] == "answered"]
    nonanswers = [row for row in records if row["expected_status"] == "insufficient_evidence"]
    completed = sum(row["attempted"] and row["protocol_valid"] and row["response_contract_valid"] and row["observed_status"] != "error" for row in records)
    correct = sum(row["final_correct"] is True for row in records)
    incorrect = sum(row["final_correct"] is False for row in records)
    pending = total - correct - incorrect
    times = [row["total_seconds"] for row in records if row["total_seconds"] is not None]
    calls_complete = all(row["generation_posts_attempted"] is not None for row in records)
    reviewed_claims = [row for row in records if (row.get("semantic_review") or {}).get("supported_claims") is not None]
    answered = [row for row in records if row["observed_status"] == "answered"]
    return {"scheduled_questions": total, "attempted": sum(row["attempted"] for row in records),
        "technical_completions": completed, "technical_completion_rate": ratio(completed, total),
        "confirmed_correct": correct, "confirmed_incorrect": incorrect, "pending_or_uncertain": pending,
        "question_accuracy": ratio(correct, total) if pending == 0 else None,
        "answerable": {"scheduled": len(answerable), "confirmed_correct": sum(row["final_correct"] is True for row in answerable),
            "false_abstention_statuses": sum(row["observed_status"] == "insufficient_evidence" for row in answerable)},
        "nonanswers": {"scheduled": len(nonanswers), "confirmed_correct": sum(row["final_correct"] is True for row in nonanswers),
            "unexpected_answer_statuses": sum(row["observed_status"] == "answered" for row in nonanswers),
            "nonempty_packets": sum(row["packet_nonempty"] is True for row in nonanswers)},
        "retrieval_hit_at_5": {"hits": sum(row["reference_hit_at_5"] is True for row in answerable), "denominator": len(answerable),
            "unobserved": sum(row["reference_hit_at_5"] is None for row in answerable)},
        "delivered_reference_coverage": {"complete": sum(row["all_reference_spans_delivered"] is True for row in answerable), "denominator": len(answerable),
            "unobserved": sum(row["all_reference_spans_delivered"] is None for row in answerable)},
        "citation_integrity": {"mechanically_valid_answers": sum(row["mechanical_citation_valid"] is True for row in answered), "answered": len(answered)},
        "citation_support": {"supported_claims": sum(row["semantic_review"]["supported_claims"] for row in reviewed_claims),
            "reviewed_claims": sum(row["claim_count"] for row in reviewed_claims),
            "rate": ratio(sum(row["semantic_review"]["supported_claims"] for row in reviewed_claims), sum(row["claim_count"] for row in reviewed_claims))},
        "generation_posts_attempted": sum(row["generation_posts_attempted"] for row in records) if calls_complete else None,
        "generation_requests_in_logs": sum(row["generation_requests_in_log"] for row in records),
        "format_retries": sum(row["format_retries"] for row in records) if all(row["format_retries"] is not None for row in records) else None,
        "latency_seconds": {"observations": len(times), "first": times[0] if times else None,
            "warm_median": median(times[1:]) if len(times) > 1 else None, "total": sum(times)},
        "model_startup_seconds": None, "device_memory_measured": False,
        "software_tests_are_not_question_accuracy": True}


def document_scores(template, review_path=None):
    by_id = {row["transcription_id"]: row for row in template}
    reviews = {}
    if review_path is not None:
        for row in read_jsonl(review_path):
            identity = row["transcription_id"]
            if identity not in by_id or identity in reviews or set(row) != set(by_id[identity]):
                raise ValueError("Unknown, repeated or malformed document review")
            original = by_id[identity]
            if row["review_binding"] != original["review_binding"] or row["stratum"] != original["stratum"]:
                raise ValueError("Document review belongs to a different sample/dataset/run")
            values = (row["correct_projection"], row["structural_error"])
            if any(value is not None and type(value) is not bool for value in values):
                raise ValueError("Document decisions must be boolean or pending")
            if any(value is not None for value in values):
                if (None in values or not isinstance(row["reviewer"], str) or not row["reviewer"].strip()
                        or not isinstance(row["notes"], str) or values == (True, True)):
                    raise ValueError("Inconsistent or unnamed document review")
            reviews[identity] = row
    rows = [reviews.get(row["transcription_id"], row) for row in template]
    completed = [row for row in rows if row["correct_projection"] is not None]
    count = len(completed)
    correct = sum(row["correct_projection"] for row in completed)
    structural = sum(row["structural_error"] for row in completed)
    return rows, {"planned": len(template), "reviewed": count, "pending": len(template) - count,
        "correct_documents": correct if count else None, "structural_error_documents": structural if count else None,
        "correctly_processed_rate": correct / count if count else None,
        "structural_error_rate": structural / count if count else None,
        "meets_sample_targets": (correct / count >= .8 and structural / count < .05) if count == len(template) and count else None,
        "corpus_representativeness_established": False}
