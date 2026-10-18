"""Stable UI boundary for source search and explicitly requested cited answers."""

from contracts import AnswerResponse, SourceCard


def search_records(query: str, transcription_id: int | None = None) -> list[SourceCard]:
    from core.search import search_records as search
    return search(query, transcription_id)


def answer_question(question: str, transcription_id: int | None = None) -> AnswerResponse:
    from core.answering import run_answer
    result, _ = run_answer(question, transcription_id)
    return result
