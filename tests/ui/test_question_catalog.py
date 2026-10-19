"""Bounded UI checks; all live backend/model access is forbidden."""

import json

import pytest

import app
from ui.question_catalog import EXAMPLES, load_examples, question_choices, question_input


@pytest.fixture(autouse=True)
def no_backend(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Selection must not call the backend or network")
    monkeypatch.setattr(app.service, "answer_question", forbidden)
    monkeypatch.setattr("httpx.Client.send", forbidden)


def test_all_fifty_examples_match_benchmark_inputs_without_answer_fields():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2] / "evaluation/references/draft-v1"
    expected = {}
    for split, count in [("development", 20), ("evaluation", 30)]:
        references = [json.loads(line) for line in (root / f"{split}-questions.jsonl").read_text().splitlines()]
        assert len(references) == count == len(question_choices(split))
        for ref in references:
            expected[ref["case_id"]] = {"case_id": ref["case_id"], "split": split, **ref["input"]}
    assert len(EXAMPLES) == 50 and EXAMPLES == expected


def test_every_selection_populates_exact_question_and_clears_old_results():
    for cid, row in EXAMPLES.items():
        text, scope, status, answer, sources = app.on_question_select(cid, row["split"])
        assert text == row["question"]
        assert scope == ("" if row["transcription_id"] is None else str(row["transcription_id"]))
        assert "Click Ask" in status.value and not answer and not sources


def test_archive_wide_selection_clears_previous_scope():
    assert question_input("DEV-01", "development")[1] == "16"
    assert question_input("EVAL-01", "evaluation")[1] == ""
    assert question_input("EVAL-27", "evaluation")[1] == ""


def test_custom_and_split_changes_clear_selection_question_scope_and_answer():
    for split in ("custom", "development", "evaluation"):
        dropdown, question, scope, _, answer, source = app.on_question_set_change(split)
        assert dropdown.value is None
        assert not question and not scope and not answer and not source
        assert dropdown.interactive == (split != "custom")
    assert question_choices("custom") == []
    assert app.question_set.value == "custom" and app.example_question.value is None
    assert app.question.interactive is not False and app.transcription_id.interactive is not False


def test_invalid_or_wrong_split_selection_never_guesses_inputs():
    for cid, split in [("EVAL-01", "development"), ("missing", "evaluation")]:
        question, scope, status, answer, source = app.on_question_select(cid, split)
        assert not question and not scope and not answer and not source
        assert "Choose a question" in status.value
    assert app.on_question_select(None, "development")[0:2] == ("", "")


def test_demo_disables_benchmark_selectors():
    radio, dropdown = app.on_question_mode("demo", "development")
    assert radio.interactive is False and dropdown.interactive is False
    radio, dropdown = app.on_question_mode("live", "development")
    assert radio.interactive is True and dropdown.interactive is True


def test_runtime_catalog_rejects_answer_bearing_fields(tmp_path):
    path = tmp_path / "examples.json"
    row = dict(EXAMPLES["DEV-01"], required_facts=["not allowed"])
    path.write_text(json.dumps([row]), encoding="utf-8")
    with pytest.raises(ValueError, match="only question inputs"):
        load_examples(path)


def test_only_question_and_scope_reach_live_service_after_selection(monkeypatch):
    calls = []
    from ui.demo import load_demo_response
    response = load_demo_response()
    response["mode"] = "live"
    monkeypatch.setattr(app.service, "answer_question", lambda *args: calls.append(args) or response)
    text, scope, *_ = app.on_question_select("DEV-01", "development")
    app.on_ask(text, scope, mode="live")
    assert calls == [(EXAMPLES["DEV-01"]["question"], 16)]
