"""S1 checks: demo label, separate answer/source, faithful original text."""
import app
from app import DEMO_BANNER, format_source, on_ask


def test_ask_shows_demo_label_answer_and_source():
    banner, status, answer, source = on_ask("any question", None)
    assert banner == DEMO_BANNER
    assert status.startswith("Answered")
    assert answer == "The passage names the place as Hörndli."
    assert "Hörndli, heist der Ort, wo die $ Schull $$ ist." in source
    assert "stapfer:answer:41" in source


def test_missing_page_is_not_verified_not_zero():
    card = {
        "record_id": "stapfer:answer:41",
        "transcription_id": 16,
        "question_number": "I.1",
        "text_original": "Hörndli",
        "archive_reference": None,
        "pdf_page_index": None,
    }
    text = format_source(card)
    assert "Page: Page not verified" in text
    assert "Page: 0" not in text
    assert "Archive reference: unknown" in text

def test_insufficient_evidence_shows_reason_and_no_answer():
    banner, status, answer, source = on_ask("q", None, "insufficient")
    assert banner == DEMO_BANNER
    assert status.startswith("Not enough evidence to answer")
    assert answer == ""
    assert source == ""


def test_error_shows_failure_and_no_answer():
    banner, status, answer, source = on_ask("q", None, "error")
    assert banner == DEMO_BANNER
    assert status.startswith("Error")
    assert answer == ""
    assert source == ""


def test_error_after_answer_leaves_no_stale_answer():
    _, _, first_answer, first_source = on_ask("q", None, "answered")
    assert "Hörndli" in first_answer

    _, status, answer, source = on_ask("q", None, "error")
    assert status.startswith("Error")
    assert "Hörndli" not in answer
    assert "Hörndli" not in source


def test_crash_becomes_error_with_empty_boxes(monkeypatch):
    def broken_loader(name):
        raise ConnectionError("model server unreachable")

    monkeypatch.setattr(app, "load_demo_response", broken_loader)

    banner, status, answer, source = on_ask("q", None, "answered")
    assert status.startswith("Error")
    assert "model server unreachable" in status
    assert answer == ""
    assert source == ""