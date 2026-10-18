"""Shared UI boundary: J2 source search; generation remains a separate J3 task."""

from contracts import AnswerResponse, SourceCard


def search_records(query: str, transcription_id: int | None = None) -> list[SourceCard]:
    from core.search import search_records as search
    return search(query, transcription_id)


def answer_question(question: str, transcription_id: int | None = None) -> AnswerResponse:
    raise NotImplementedError("J3: archival evidence retrieval and answering are not connected yet")
