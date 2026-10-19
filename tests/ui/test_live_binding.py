"""LIVE dispatch and wording checks; no inference or historical grading."""

import pytest

import app
from core import answering, service
from ui.demo import load_demo_response


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Real HTTP/model calls are forbidden in software checks")
    monkeypatch.setattr("httpx.Client.send", denied)


@pytest.mark.parametrize("scope", [None, 16, 2069])
def test_live_service_uses_frozen_method_without_extra_inputs(monkeypatch, scope):
    calls = []
    response = dict(load_demo_response(), mode="live")
    monkeypatch.setattr(answering, "run_answer",
        lambda *args, **kwargs: calls.append((args, kwargs)) or (response, None))
    assert service.answer_question("An editable user question", scope) is response
    assert calls == [(("An editable user question", scope),
                      {"pipeline": "apertus-qualified", "retrieval_mode": "bound"})]


def test_answer_produced_never_becomes_a_correctness_grade():
    response = dict(load_demo_response(), mode="live")
    shown = app.format_status(response)
    assert shown.startswith("Answer produced — not human-reviewed")
    assert "Valid citations do not prove correctness" in shown
    assert response["status"] == "answered"
    assert "fresh attempt" in app.LIVE_BANNER and "recorded result" in app.LIVE_BANNER


def test_insufficient_evidence_is_not_relabelled_as_an_answer():
    response = dict(load_demo_response("insufficient"), mode="live")
    assert app.format_status(response).startswith("Not enough evidence to answer")
    assert response["status"] == "insufficient_evidence" and response["answer"] is None


def test_demo_scenario_is_hidden_by_default_and_fixture_remains_labelled():
    assert app.scenario.visible is False
    assert app.format_status(load_demo_response()).startswith("Demo answer — scripted example")
