"""Shared UI/backend shapes. Jean integrates changes after team agreement."""

from typing import Literal, TypedDict


class SourceCard(TypedDict):
    record_id: str
    transcription_id: int
    question_number: str | None
    text_original: str
    archive_reference: str | None
    pdf_page_index: int | None


class AnswerResponse(TypedDict):
    mode: Literal["demo", "live"]
    status: Literal["answered", "insufficient_evidence", "error"]
    answer: str | None
    sources: list[SourceCard]
    message: str | None


def validate_response(value: dict) -> None:
    """Mechanical UI contract only; not semantic/citation verification."""
    if set(value) != {"mode", "status", "answer", "sources", "message"}:
        raise ValueError("Unexpected response fields")
    if value["mode"] not in ("demo", "live") or value["status"] not in (
        "answered", "insufficient_evidence", "error"
    ):
        raise ValueError("Unknown mode/status")
    if not isinstance(value["sources"], list):
        raise ValueError("sources must be a list")
    if value["status"] == "answered":
        if not isinstance(value["answer"], str) or not value["answer"].strip() or not value["sources"]:
            raise ValueError("Answered responses require text and sources")
    elif value["answer"] is not None:
        raise ValueError("Nonanswers must not retain an earlier answer")
    if value["message"] is not None and not isinstance(value["message"], str):
        raise ValueError("message must be text or null")
    for source in value["sources"]:
        if set(source) != set(SourceCard.__annotations__):
            raise ValueError("Unexpected source fields")
        if type(source["transcription_id"]) is not int or source["transcription_id"] < 1:
            raise ValueError("Invalid transcription ID")
        if not isinstance(source["record_id"], str) or not source["record_id"].startswith("stapfer:answer:"):
            raise ValueError("Invalid source ID")
        if not isinstance(source["text_original"], str) or not source["text_original"].strip():
            raise ValueError("Missing original text")
        for field in ("question_number", "archive_reference"):
            if source[field] is not None and not isinstance(source[field], str):
                raise ValueError(f"Invalid {field}")
        page = source["pdf_page_index"]
        if page is not None and (type(page) is not int or page < 0):
            raise ValueError("Invalid page index")
