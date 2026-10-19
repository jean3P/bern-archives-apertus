"""Stable UI boundary for source search and explicitly requested cited answers."""

from contracts import AnswerResponse, SourceCard

LIVE_PIPELINE = "apertus-qualified"
LIVE_RETRIEVAL_MODE = "bound"


def search_records(query: str, transcription_id: int | None = None) -> list[SourceCard]:
    from core.search import search_records as search
    return search(query, transcription_id)


def answer_question(question: str, transcription_id: int | None = None) -> AnswerResponse:
    """Use the frozen reviewed method for LIVE; never replay a benchmark answer."""
    from core.answering import run_answer
    result, _ = run_answer(question, transcription_id,
                           pipeline=LIVE_PIPELINE, retrieval_mode=LIVE_RETRIEVAL_MODE)
    return result
