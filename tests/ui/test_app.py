"""S1 checks: demo label, separate answer/source, faithful original text."""

from app import DEMO_BANNER, format_source, on_ask


def test_ask_shows_demo_label_answer_and_source():
    banner, answer, source = on_ask("any question", None)
    assert banner == DEMO_BANNER
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