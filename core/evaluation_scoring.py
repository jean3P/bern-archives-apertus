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


def inspect_case(case, directory, observation, aliases, authority, *, pipeline="apertus"):
    try:
        return _inspect_case(case, directory, observation, aliases, authority, pipeline=pipeline)
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


def _inspect_case(case, directory, observation, aliases, authority, *, pipeline="apertus"):
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
    if pipeline not in ("apertus", "apertus-qualified", "qwen-only", "apertus-facets", "qwen-apertus"):
        raise ValueError("Unknown inspection pipeline")
    cap = 4 if pipeline == "qwen-apertus" else 3
    budget_valid = (not attempted or (type(calls) is int and 0 <= calls <= cap and calls == len(requests)
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
    if attempted and pipeline == "qwen-apertus":
        protocol_valid = protocol_valid and hybrid_receipts_valid(saved, events, delivered=None)
    if attempted and pipeline == "apertus-facets":
        protocol_valid = protocol_valid and parts_receipts_valid(saved, events, delivered=None)
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
    if attempted and pipeline == "qwen-apertus" and status != "error":
        protocol_valid = protocol_valid and hybrid_receipts_valid(saved, events, delivered=delivered)
    if attempted and pipeline == "apertus-facets" and status != "error":
        protocol_valid = protocol_valid and parts_receipts_valid(saved, events, delivered=delivered)
    if attempted and pipeline in ("apertus-qualified", "qwen-only"):
        protocol_valid = protocol_valid and qualifications_receipts_valid(saved, events, delivered, pipeline=pipeline)
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


def qualifications_receipts_valid(saved, events, delivered, *, pipeline="apertus-qualified"):
    from core import answer_qualifications as aq
    if saved("input.json", {}).get("retrieval_mode") == "coverage":
        from core.answer_coverage import receipts_valid
        return (pipeline in ("apertus-qualified", "qwen-only")
                and saved("input.json", {}).get("pipeline") == pipeline
                and receipts_valid(saved, events, delivered))
    implementation = saved("implementation.json", {})
    version = implementation.get("version")
    if pipeline not in ("apertus-qualified", "qwen-only"):
        return False
    model = aq.QWEN_MODEL if pipeline == "qwen-only" else aq.MODEL
    versions = (aq.VERSION,) if pipeline == "qwen-only" else (aq.VERSION, aq.ORIGINAL_VERSION, aq.LEGACY_VERSION)
    if (version not in versions or implementation.get("model") != model
            or saved("input.json", {}).get("pipeline") != pipeline
            or saved("summary.json", {}).get("pipeline") != pipeline):
        return False
    pending, answers = None, []
    for event in events:
        if event.get("event") == "generation_request":
            stage, body = event.get("stage"), event.get("request", {})
            limit = {"retrieval_plan": 180, "cited_answer": 512}.get(stage)
            if pending is not None or limit is None or body.get("model") != model or body.get("max_tokens") != limit:
                return False
            pending = stage
        elif event.get("event") == "generation_response":
            if event.get("stage") != pending or event.get("http_status") != 200:
                return False
            wire = strict_loads(event["body"])
            if wire.get("model") != model or len(wire.get("choices", [])) != 1:
                return False
            if wire["choices"][0].get("finish_reason") != "stop":
                return False
            if pending == "cited_answer":
                answers.append(wire["choices"][0]["message"]["content"])
            pending = None
        elif event.get("event") == "generation_transport_error":
            if saved("summary.json", {}).get("status") != "error" or event.get("stage") != pending:
                return False
            pending = None
    if pending is not None:
        return False
    if saved("summary.json", {}).get("status") == "error":
        return True
    if saved("input.json", {}).get("retrieval_mode") == "entity":
        from core.entity_retrieval import receipts_valid
        if not receipts_valid(saved, events):
            return False
    if not delivered:
        return not answers
    raw = strict_loads(answers[-1])
    return raw == saved("qualification_answer.json", None) and aq.normalize(raw, delivered, version) == saved("validated_claims.json", None)


def parts_receipts_valid(saved, events, delivered):
    from core import facet_answering as fa
    from core.evidence import explicit_codes
    request, summary, implementation = saved("input.json", {}), saved("summary.json", {}), saved("implementation.json", {})
    if (request.get("pipeline") != "apertus-facets" or summary.get("pipeline") != "apertus-facets"
            or implementation.get("version") != fa.VERSION
            or implementation.get("stage_models") != {stage: fa.MODEL for stage in fa.TOKENS}
            or implementation.get("stage_token_limits") != fa.TOKENS):
        return False
    pending, stages, returned = None, [], {}
    for event in events:
        if event.get("event") == "generation_request":
            stage, body = event.get("stage"), event.get("request", {})
            if (pending is not None or stage not in fa.TOKENS or body.get("model") != fa.MODEL
                    or body.get("max_tokens") != fa.TOKENS[stage] or body.get("temperature") != 0):
                return False
            stages.append(stage)
            pending = stage
        elif event.get("event") == "generation_response":
            if pending != event.get("stage"):
                return False
            if summary.get("status") != "error":
                wire = strict_loads(event["body"])
                if event.get("http_status") != 200 or wire.get("model") != fa.MODEL or len(wire.get("choices", [])) != 1:
                    return False
                choice = wire["choices"][0]
                if choice.get("finish_reason") != "stop":
                    return False
                returned[pending] = choice["message"]["content"]
            pending = None
        elif event.get("event") == "generation_transport_error":
            if summary.get("status") != "error" or pending != event.get("stage"):
                return False
            pending = None
    order = list(fa.TOKENS)
    retries = sum(max(0, stages.count(stage) - 1) for stage in order)
    if pending is not None or stages != sorted(stages, key=order.index) or retries > 1:
        return False
    if delivered is None or summary.get("status") == "error":
        return True
    if retries != summary.get("format_retries"):
        return False
    catalogue = saved("question_catalogue.json", [])
    parsed = strict_loads(returned["question_interpretation"])
    fa.validate_interpretation(parsed, catalogue, request["transcription_id"] is not None,
                               explicit_codes(request["question"], catalogue), request["question"])
    if saved("question_interpretation.json", {}) != {"model_output": parsed, "facets": fa.bind_facets(parsed)}:
        return False
    if not delivered:
        return "cited_answer" not in stages
    parts = strict_loads(returned["cited_answer"])
    normalized = fa.validate_parts(parts, parsed, delivered)
    return parts == saved("part_answers.json", None) and normalized == saved("validated_claims.json", None)


def hybrid_receipts_valid(saved, events, delivered):
    """Replay the hybrid contract offline; no question correctness or new model calls."""
    from core import question_evidence as qe
    from core.evidence import explicit_codes
    request, summary = saved("input.json", {}), saved("summary.json", {})
    implementation = saved("implementation.json", {})
    if (request.get("pipeline") != "qwen-apertus" or summary.get("pipeline") != "qwen-apertus"
            or implementation.get("version") != qe.HYBRID_VERSION
            or implementation.get("stage_models") != qe.STAGE_MODELS
            or implementation.get("stage_token_limits") != qe.STAGE_TOKENS
            or implementation.get("max_generation_posts") != 4
            or implementation.get("max_shared_validation_retries") != 1):
        return False
    pending, stages, returned = None, [], {}
    for event in events:
        if event.get("event") == "generation_request":
            stage, body = event.get("stage"), event.get("request", {})
            if (pending is not None or stage not in qe.STAGE_MODELS
                    or body.get("model") != qe.STAGE_MODELS[stage]
                    or body.get("max_tokens") != qe.STAGE_TOKENS[stage] or body.get("temperature") != 0):
                return False
            stages.append(stage)
            pending = stage
        elif event.get("event") == "generation_response":
            if pending is None or event.get("stage") != pending:
                return False
            if event.get("http_status") == 200:
                wire = strict_loads(event["body"])
                if wire.get("model") != qe.STAGE_MODELS[pending]:
                    return False
                choices = wire.get("choices", [])
                if len(choices) != 1 or choices[0].get("finish_reason") != "stop":
                    if summary.get("status") != "error":
                        return False
                else:
                    returned[pending] = choices[0].get("message", {}).get("content")
            elif summary.get("status") != "error":
                return False
            pending = None
        elif event.get("event") == "generation_transport_error":
            if event.get("stage") != pending or summary.get("status") != "error":
                return False
            pending = None
    order = list(qe.STAGE_MODELS)
    if (pending is not None or stages != sorted(stages, key=order.index)
            or any(stages.count(stage) > 2 for stage in order)
            or sum(max(0, stages.count(stage) - 1) for stage in order) > 1):
        return False
    if summary.get("status") != "error" and sum(max(0, stages.count(stage) - 1) for stage in order) != summary.get("format_retries"):
        return False
    if delivered is None or summary.get("status") == "error":
        return True
    catalogue = saved("question_catalogue.json", [])
    interpretation = saved("question_interpretation.json", {})
    parsed = strict_loads(returned["question_interpretation"])
    qe.validate_interpretation(parsed, catalogue, request["transcription_id"] is not None,
                               explicit_codes(request["question"], catalogue))
    facets = qe.bind_facets(parsed)
    if interpretation != {"model_output": parsed, "facets": facets}:
        return False
    if not delivered:
        return stages.count("evidence_extraction") == stages.count("cited_answer") == 0
    extracted = strict_loads(returned["evidence_extraction"])
    qe.validate_extraction(extracted, facets, delivered)
    final = strict_loads(returned["cited_answer"])
    legacy = qe.validate_final(final, parsed, extracted, delivered)
    return (extracted == saved("evidence_extraction.json", None)
            and final == saved("facet_answer.json", None)
            and legacy == saved("validated_claims.json", None))


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
