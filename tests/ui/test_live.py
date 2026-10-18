"""M1 UI-to-service software controls. No real archive or model requests."""

from copy import deepcopy

import pytest

import app
from ui.demo import load_demo_response


@pytest.fixture(autouse=True)
def forbid_real_service(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Real backend is forbidden in UI software tests")
    monkeypatch.setattr(app.service, "answer_question", denied)
    monkeypatch.setattr("httpx.Client.send", denied)


def live_response(scenario="answered"):
    value = deepcopy(load_demo_response(scenario))
    value["mode"] = "live"
    return value


def test_optional_transcription_component_starts_blank():
    assert app.transcription_id.value is None
    assert app.transcription_id.get_config()["value"] is None
    assert app.transcription_id.preprocess(None) is None


def test_live_passes_actual_question_and_normalized_scope(monkeypatch):
    calls = []
    def answer(question, scope):
        calls.append((question, scope))
        return live_response()
    monkeypatch.setattr(app.service, "answer_question", answer)
    banner, status, text, source = app.on_ask("Actual user question", 16.0, mode="live")
    assert calls == [("Actual user question", 16)]
    assert banner == app.LIVE_BANNER and "Answered" in status.value
    assert "Hörndli" in text and "stapfer:answer:41" in source


def test_live_blank_scope_is_none_and_does_not_reuse_a_previous_id(monkeypatch):
    calls = []
    monkeypatch.setattr(app.service, "answer_question", lambda question, scope: calls.append(scope) or live_response())
    app.on_ask("q", 16, mode="live")
    app.on_ask("q", None, mode="live")
    assert calls == [16, None]


@pytest.mark.parametrize("value", [-1, 0, 16.5, True, "16.5", "bad", float("nan"), float("inf")])
def test_bad_scope_never_reaches_the_backend(monkeypatch, value):
    calls = []
    monkeypatch.setattr(app.service, "answer_question", lambda *args: calls.append(args))
    banner, status, text, source = app.on_ask("q", value, mode="live")
    assert not calls and banner == app.LIVE_BANNER
    assert "Error" in status.value and not text and not source
    assert "positive whole transcription ID" in status.value
    assert "leave it blank" in status.value
    assert "ValueError" not in status.value


@pytest.mark.parametrize("question", [None, "", "   ", "x" * 2001])
def test_bad_question_never_reaches_the_backend(monkeypatch, question):
    calls = []
    monkeypatch.setattr(app.service, "answer_question", lambda *args: calls.append(args))
    _, status, text, source = app.on_ask(question, 16, mode="live")
    assert not calls and "Error" in status.value and not text and not source
    assert "Enter a question of 1–2000 characters." in status.value
    assert "ValueError" not in status.value


def test_nonanswer_clears_answer_but_preserves_context_sources(monkeypatch):
    positive = live_response()
    negative = {"mode": "live", "status": "insufficient_evidence", "answer": None,
        "sources": positive["sources"], "message": "No exact GPS coordinates in the supplied passage."}
    replies = iter([positive, negative])
    monkeypatch.setattr(app.service, "answer_question", lambda *args: next(replies))
    assert app.on_ask("q", 16, mode="live")[2]
    banner, status, text, source = app.on_ask("GPS?", 16, mode="live")
    assert banner == app.LIVE_BANNER and "Not enough evidence" in status.value
    assert text == "" and "stapfer:answer:41" in source


@pytest.mark.parametrize("error_type", [ConnectionError, ValueError])
def test_live_exception_is_not_a_demo_fallback_and_leaks_no_exception_details(monkeypatch, error_type):
    def broken(*args):
        raise error_type("PRIVATE_ENDPOINT_AND_TOKEN")
    monkeypatch.setattr(app.service, "answer_question", broken)
    monkeypatch.setattr(app, "load_demo_response", lambda *args: pytest.fail("Fixture fallback forbidden"))
    banner, status, text, source = app.on_ask("q", 16, mode="live")
    assert banner == app.LIVE_BANNER and "check the service configuration" in status.value
    assert error_type.__name__ not in status.value
    assert "PRIVATE_ENDPOINT" not in status.value and text == "" and source == ""


def test_live_rejects_demo_or_malformed_responses(monkeypatch):
    for value in [load_demo_response(), {"status": "answered"}]:
        monkeypatch.setattr(app.service, "answer_question", lambda *args: value)
        _, status, text, source = app.on_ask("q", 16, mode="live")
        assert "Error" in status.value and text == "" and source == ""


def test_backend_error_clears_all_old_answer_content(monkeypatch):
    monkeypatch.setattr(app.service, "answer_question", lambda *args: live_response("error"))
    banner, status, text, source = app.on_ask("q", 16, mode="live")
    assert banner == app.LIVE_BANNER and "Error" in status.value and not text and not source


def test_mode_change_and_request_start_clear_visible_results():
    scenario, banner, status, text, source = app.on_mode_change("demo")
    assert scenario.interactive is True and banner == app.DEMO_BANNER and not text and not source
    scenario, banner, _, text, source = app.on_mode_change("live")
    assert scenario.interactive is False and banner == app.LIVE_BANNER and not text and not source
    banner, status, text, source = app.clear_response("live")
    assert banner == app.LIVE_BANNER and status.value == "Working…" and not text and not source


def test_number_component_does_not_round_fractional_scope_before_validation(monkeypatch):
    calls = []
    monkeypatch.setattr(app.service, "answer_question", lambda *args: calls.append(args))
    supplied = app.transcription_id.preprocess(16.5)
    assert supplied == 16.5
    _, status, text, source = app.on_ask("q", supplied, mode="live")
    assert not calls and "Error" in status.value and not text and not source


def test_existing_demo_path_never_calls_live_service():
    banner, status, text, source = app.on_ask("ignored fixture input", None, mode="demo")
    assert banner == app.DEMO_BANNER and "Answered" in status.value and "Hörndli" in text
