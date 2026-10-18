"""Read-only evidence assembly over the completed J2 index. No model calls."""

import json
import re

from core.search import open_index, source_card

MAX_GROUPS = 5
MAX_PASSAGE_CHARS = 2000
MAX_PACKET_CHARS = 11000


class EvidenceStore:
    def __init__(self, directory):
        # Existing source/receipt/index-hash checks run before any read.
        self.connection = open_index(directory)

    def close(self):
        self.connection.close()

    def catalogue(self):
        return [json.loads(row[0]) for row in self.connection.execute(
            "SELECT payload FROM questions ORDER BY id")]

    def records(self, cards):
        records = []
        for card in cards:
            found = self.connection.execute(
                "SELECT payload FROM answers WHERE record_id=?", (card["record_id"],)).fetchone()
            if found is None:
                raise ValueError("A retrieved source is absent from the completed index")
            record = json.loads(found[0])
            if source_card(record) != card:
                raise ValueError("Retrieved card differs from its original record")
            records.append(record)
        return records


def explicit_codes(question, catalogue):
    known = {row["question_number"].casefold(): row["question_number"]
             for row in catalogue if row["question_number"]}
    codes = []
    for match in re.finditer(r"\b(?:IV|III|II|I)\.\d+(?:\.[a-z])?\b", question, re.I):
        code = known.get(match.group().casefold())
        if code is None:
            raise ValueError("The supplied survey question code is not in the dataset")
        if code not in codes:
            codes.append(code)
    if len(codes) > 3:
        raise ValueError("Use at most three explicit survey question codes")
    return codes


def make_packet(records, catalogue):
    """Group equal text only within one transcription; keep every included ID."""
    questions = {row["question_id"]: row for row in catalogue}
    grouped = {}
    for record in records:
        text = record["text_original"]
        if isinstance(text, str) and text.strip():
            grouped.setdefault((record["transcription_id"], text), []).append(record)
    packet, included, omitted = [], {}, []
    for (transcription, text), members in grouped.items():
        group = {"transcription_id": transcription, "passage": text[:MAX_PASSAGE_CHARS],
                 "passage_complete": len(text) <= MAX_PASSAGE_CHARS,
                 "character_start": 0, "character_end": min(len(text), MAX_PASSAGE_CHARS),
                 "records": []}
        for row in members:
            original_question = questions[row["question_id"]]
            group["records"].append({
                "record_id": row["record_id"], "question_number": row["question_number"],
                "survey_question": original_question["text_original"],
                "survey_question_french": original_question["text_french"],
                "school_ids_are_context_only": True, "school_ids": row["school_ids"],
                "school_assignment_source_raw": row["school_assignment_source_raw"],
                "school_assignment_interpreted": False,
                "quality_flags": row["quality_flags"],
                "archive_reference": row["archive_reference"],
                "pdf_page_index": row["pdf_page_index"]})
        candidate_size = len(json.dumps(packet + [group], ensure_ascii=False))
        if len(packet) >= MAX_GROUPS or candidate_size > MAX_PACKET_CHARS:
            omitted.extend(row["record_id"] for row in members)
            continue
        packet.append(group)
        for row in members:
            included[row["record_id"]] = {"record": row, "delivered_passage": group["passage"]}
    return packet, included, omitted


def validate_answer(value, included):
    """Mechanical citation checks only. Does not establish claim entailment."""
    if not isinstance(value, dict) or set(value) != {"status", "claims", "message"}:
        raise ValueError("Use exactly status, claims and message")
    if value["status"] not in ("answered", "insufficient_evidence"):
        raise ValueError("Unknown answer status")
    claims, message = value["claims"], value["message"]
    if not isinstance(claims, list) or not isinstance(message, str) or len(message) > 500:
        raise ValueError("Invalid claims/message types or length")
    if value["status"] == "insufficient_evidence":
        if claims or not message.strip():
            raise ValueError("Insufficient evidence requires no claims and a message")
        return value
    if not 1 <= len(claims) <= 5:
        raise ValueError("An answer requires one to five cited claims")
    for claim in claims:
        if not isinstance(claim, dict) or set(claim) != {"text", "citations"}:
            raise ValueError("Each claim needs exactly text and citations")
        text, citations = claim["text"], claim["citations"]
        if not isinstance(text, str) or not text.strip() or len(text) > 600:
            raise ValueError("Claim text is empty or too long")
        if "stapfer:" in text or re.search(r"https?://", text):
            raise ValueError("Put source IDs in citations, not claim text or URLs")
        if not isinstance(citations, list) or not 1 <= len(citations) <= 3:
            raise ValueError("Each claim needs one to three citations")
        for citation in citations:
            if not isinstance(citation, dict) or set(citation) != {"record_id", "quote"}:
                raise ValueError("Citations contain only record_id and quote; no invented metadata")
            record_id, quote = citation["record_id"], citation["quote"]
            if not isinstance(record_id, str) or record_id not in included:
                raise ValueError("A cited record ID was not supplied in the evidence packet")
            if not isinstance(quote, str) or len(quote.strip()) < 3 or len(quote) > 2000:
                raise ValueError("A supporting quote is empty or invalid")
            if quote not in included[record_id]["delivered_passage"]:
                raise ValueError("A quote is not an exact span of the supplied original passage")
    return value


def format_answer(value, included):
    """Attach metadata from software, never from model-generated source cards."""
    if value["status"] == "insufficient_evidence":
        return {"mode": "live", "status": "insufficient_evidence", "answer": None,
                "sources": [source_card(item["record"]) for item in included.values()],
                "message": value["message"]}
    lines, ids = [], []
    for claim in value["claims"]:
        cited = list(dict.fromkeys(item["record_id"] for item in claim["citations"]))
        lines.append(claim["text"].strip() + " " + " ".join("[" + key + "]" for key in cited))
        ids.extend(key for key in cited if key not in ids)
    records = [included[key]["record"] for key in ids]
    message = value["message"].strip() or None
    if any(len(row["school_ids"]) > 1 or "uninterpreted_school_assignment" in row["quality_flags"]
           for row in records):
        warning = "School links are transcription context; school-specific attribution remains unresolved."
        message = (message + " " if message else "") + warning
    return {"mode": "live", "status": "answered", "answer": "\n\n".join(lines),
            "sources": [source_card(row) for row in records], "message": message}
