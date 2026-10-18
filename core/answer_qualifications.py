"""One additional answer field; reuse the original retrieval and quote validator."""

from copy import deepcopy

from core.evidence import validate_answer

VERSION = "cited-answer-v5-visible-qualifications"
MODEL = "swiss-ai/Apertus-v1.5-8B"
INSTRUCTIONS = """
Each claim additionally has qualifications, a string displayed immediately after its text.
Write the direct answer in text. Write ALL relevant conditions, exceptions and meaning-changing
qualifiers supported by that claim's citations in qualifications; use an empty string only when
none apply. Do not leave a requested original term or exception only inside a quotation.
Read the full supplied passage, including its ending, before filling qualifications. Distinguish
what is prescribed from what actually occurs. Text plus qualifications must fit 600 characters.
A nonempty message is allowed for an explanation or genuine limitation; it does not invalidate
an otherwise answered result. For insufficient_evidence use claims [] and explain the limitation
in message. This field does not permit unsupported facts, altered quotes or invented source IDs.
"""


def answer_schema(original):
    schema = deepcopy(original)
    claim = schema["properties"]["claims"]["items"]
    claim["required"].append("qualifications")
    claim["properties"]["qualifications"] = {"type": "string", "maxLength": 400}
    return schema


def normalize(value, included):
    if not isinstance(value, dict) or set(value) != {"status", "claims", "message"}:
        raise ValueError("Use exactly status, claims and message")
    if not isinstance(value["claims"], list):
        raise ValueError("Claims must be a list")
    claims = []
    for claim in value["claims"]:
        if not isinstance(claim, dict) or set(claim) != {"text", "qualifications", "citations"}:
            raise ValueError("Each claim needs text, qualifications and citations")
        text, qualification = claim["text"], claim["qualifications"]
        if (not isinstance(text, str) or not text.strip() or not isinstance(qualification, str)
                or len(qualification) > 400):
            raise ValueError("Claim text or qualifications have invalid types/lengths")
        claims.append({"text": " ".join(part for part in (text.strip(), qualification.strip()) if part),
                       "citations": claim["citations"]})
    return validate_answer({"status": value["status"], "claims": claims, "message": value["message"]}, included)
