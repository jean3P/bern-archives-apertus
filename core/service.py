"""Agreed boundary for future J2/J3 implementation; no mock/live confusion."""

from contracts import AnswerResponse, SourceCard


def search_records(query: str, transcription_id: int | None = None) -> list[SourceCard]:
    raise NotImplementedError("J2: the public corpus and search index have not been built yet")


def answer_question(question: str, transcription_id: int | None = None) -> AnswerResponse:
    raise NotImplementedError("J3: archival evidence retrieval and answering are not connected yet")
