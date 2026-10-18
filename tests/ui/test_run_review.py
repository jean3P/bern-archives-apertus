"""S5 saved-run review controls on small synthetic runs. No model, search or network calls."""

import json
import socket

import gradio as gr
import pytest

from core.evaluation_records import digest, seal_directory, verify_directory
from core.evaluation_scoring import load_reviews
from ui.review_records import (CORRECTIONS_FILE, REVIEW_FILE, ReviewError, RunLoadError, export_session,
                               import_session, list_exports, load_case_file, load_references, load_run,
                               make_review)
from ui.run_review import (evidence_html, on_form_edit, on_table_select, question_answer_html,
                           step_case, visible_case_ids)

# Synthetic fixture records: invented for these tests, not archival data or model output.
CASES = [
    {"case_id": "SYN-01", "observed_status": "answered", "claim_count": 1, "definitive_failure": False,
     "answer": "The place is called <b>Testdorf</b>. [stapfer:answer:1]"},
    {"case_id": "SYN-02", "observed_status": "insufficient_evidence", "claim_count": 0,
     "definitive_failure": False, "answer": None},
    {"case_id": "SYN-03", "observed_status": "error", "claim_count": 0, "definitive_failure": True,
     "answer": None},
]


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def make_run(directory, split="development", binding_prefix="a"):
    """Build and seal a tiny saved run with the same file layout as a J4 development run."""
    write(directory / "run-manifest.json", {"split": split, "created_at_utc": "2026-10-18T00:00:00+00:00",
                                            "settings": {"model": "synthetic"}, "candidate": {"git_commit": "0"},
                                            "reference_review": {"status": "draft_diagnostic"}})
    lines, references = [], []
    for number, spec in enumerate(CASES, start=1):
        case_id = spec["case_id"]
        status = spec["observed_status"]
        response = {"mode": "live", "status": status, "answer": spec["answer"], "message": None,
                    "sources": [] if spec["answer"] is None else [{
                        "record_id": "stapfer:answer:1", "transcription_id": 1, "question_number": "I.1",
                        "text_original": "Testdorf, heist der $ Ort $$.", "archive_reference": None,
                        "pdf_page_index": None}]}
        lines.append({"case_id": case_id, "input": {"question": f"Synthetic question {number}?",
                                                    "transcription_id": 1},
                      "observed_status": status, "attempted": True, "response": response,
                      "claim_count": spec["claim_count"], "definitive_failure": spec["definitive_failure"],
                      "review_binding": binding_prefix * 63 + str(number), "total_seconds": 1.0,
                      "token_usage": {"prompt_tokens": 10, "completion_tokens": 5},
                      "generation_posts_attempted": 1, "format_retries": 0})
        references.append({"case_id": case_id, "expected_status": status, "required_facts": [],
                           "evidence": []})
        write(directory / "cases" / case_id / "evidence.json",
              {"packet": [] if spec["answer"] is None else [{"passage": "Testdorf, heist der $ Ort $$.",
                                                            "records": [{"record_id": "stapfer:answer:1",
                                                                         "question_number": "I.1",
                                                                         "survey_question": "Ort?",
                                                                         "archive_reference": None,
                                                                         "pdf_page_index": None}]}]})
        (directory / "cases" / case_id / "events.jsonl").write_text(
            json.dumps({"event": "retrieval", "question_code": "I.1", "returned_record_ids": []}) + "\n",
            encoding="utf-8")
    (directory / "case-scores.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines),
                                                 encoding="utf-8")
    (directory / "references").mkdir()
    (directory / "references" / "development-questions.jsonl").write_text(
        "".join(json.dumps(ref) + "\n" for ref in references), encoding="utf-8")
    # The evaluation set must never be opened by the dashboard; invalid JSON would fail if it were.
    (directory / "references" / "evaluation-questions.jsonl").write_text("NOT FOR S5\n", encoding="utf-8")
    seal_directory(directory, "recorded")
    return directory


def inventory(directory):
    return {path.relative_to(directory).as_posix(): digest(path)
            for path in sorted(directory.rglob("*")) if path.is_file()}


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Network access is forbidden in saved-run review tests")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr("httpx.Client.send", denied)


@pytest.fixture
def run_dir(tmp_path):
    return make_run(tmp_path / "runs" / "syn-run")


@pytest.fixture
def exports(tmp_path):
    return tmp_path / "exports"


def test_loads_sealed_development_run_without_reading_evaluation_set(run_dir):
    run = load_run(run_dir)
    assert [case["case_id"] for case in run["cases"]] == ["SYN-01", "SYN-02", "SYN-03"]
    assert set(load_references(run["directory"])) == {"SYN-01", "SYN-02", "SYN-03"}


def test_rejects_missing_seal_changed_run_and_non_development_split(tmp_path, run_dir):
    with pytest.raises(RunLoadError, match="no _COMPLETE"):
        load_run(tmp_path / "nothing")
    (run_dir / "cases" / "SYN-01" / "evidence.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RunLoadError, match="changed or incomplete"):
        load_run(run_dir)
    with pytest.raises(RunLoadError, match="Only development"):
        load_run(make_run(tmp_path / "eval-run", split="evaluation"))


def test_case_files_are_allow_listed_and_paths_cannot_escape(run_dir):
    run = load_run(run_dir)
    assert load_case_file(run["directory"], "SYN-01", "evidence.json")["packet"]
    assert load_case_file(run["directory"], "SYN-01", "summary.json") is None
    for case_id, name in [("../..", "evidence.json"), ("SYN-01", "models.json"), ("SYN-01", "../_COMPLETE.json")]:
        with pytest.raises(RunLoadError):
            load_case_file(run["directory"], case_id, name)


def test_display_escapes_text_and_keeps_unknowns_unknown(run_dir):
    run = load_run(run_dir)
    answered, nonanswer = run["cases"][0], run["cases"][1]
    shown = question_answer_html(answered)
    assert "<b>Testdorf</b>" not in shown and "&lt;b&gt;Testdorf&lt;/b&gt;" in shown
    assert "No answer was produced" in question_answer_html(nonanswer)
    evidence = evidence_html(load_case_file(run["directory"], "SYN-01", "evidence.json"))
    assert "Page not verified" in evidence and "$ Ort $$" in evidence and "unknown" in evidence
    assert "Evidence file unavailable" in evidence_html(None)


def test_review_rules_match_the_scorer(run_dir):
    answered, _, failed = load_run(run_dir)["cases"]
    with pytest.raises(ReviewError, match="named human reviewer"):
        make_review(answered, " ", "Incorrect", "Not counted", "", "")
    with pytest.raises(ReviewError, match="Pending"):
        make_review(answered, "Jeni", "Pending", "1", "", "")
    with pytest.raises(ReviewError, match="between 0 and 1"):
        make_review(answered, "Jeni", "Incorrect", "2", "", "")
    with pytest.raises(ReviewError, match="all 1 claim"):
        make_review(answered, "Jeni", "Correct", "Not counted", "", "")
    with pytest.raises(ReviewError, match="failed technically"):
        make_review(failed, "Jeni", "Correct", "0", "", "")
    with pytest.raises(ReviewError, match="named human reviewer"):
        make_review(answered, "", "Pending", "Not counted", "", "a suggestion")
    review = make_review(answered, "Jeni", "Incorrect", "1", "Missing a fact", " Better answer. ")
    assert review == {"reviewer": "Jeni", "decision": "incorrect", "supported_claims": 1,
                      "notes": "Missing a fact", "suggestion": "Better answer."}


def test_filters_never_drop_failures_and_navigation_stays_in_bounds(run_dir):
    run = load_run(run_dir)
    assert visible_case_ids(run, {}, "All") == ["SYN-01", "SYN-02", "SYN-03"]
    assert visible_case_ids(run, {}, "Technical error") == ["SYN-03"]
    assert visible_case_ids(run, {}, "Pending") == ["SYN-01", "SYN-02", "SYN-03"]
    assert step_case(run, {}, "All", "SYN-03", +1) == "SYN-03"
    assert step_case(run, {}, "All", "SYN-01", -1) == "SYN-01"
    assert step_case(run, {}, "Technical error", "SYN-01", +1) == "SYN-03"


def test_export_is_scorer_compatible_separate_and_leaves_run_unchanged(run_dir, exports):
    run = load_run(run_dir)
    before = inventory(run_dir)
    reviews = {"SYN-01": make_review(run["cases"][0], "Jeni", "Incorrect", "1", "Missing a fact", "Fixed.")}
    first = export_session(run, reviews, exports)
    second = export_session(run, reviews, exports)
    assert first != second and sorted(path.name for path in first.iterdir()) == [REVIEW_FILE, CORRECTIONS_FILE]
    records = [json.loads(line) for line in (first / REVIEW_FILE).read_text(encoding="utf-8").splitlines()]
    assert [record["case_id"] for record in records] == ["SYN-01", "SYN-02", "SYN-03"]
    assert all(set(record) == {"case_id", "review_binding", "reviewer", "decision", "supported_claims", "notes"}
               for record in records)
    assert records[1]["decision"] is None and records[1]["reviewer"] is None
    assert len(load_reviews(first / REVIEW_FILE, run["cases"])) == 3
    corrections = json.loads((first / CORRECTIONS_FILE).read_text(encoding="utf-8"))
    assert corrections["label"] == "Human suggestion, not generated output"
    assert corrections["run_seal_sha256"] == digest(run_dir / "_COMPLETE.json")
    assert [item["suggested_answer"] for item in corrections["corrections"]] == ["Fixed."]
    assert run["cases"][0]["response"]["answer"].startswith("The place is called")
    assert inventory(run_dir) == before
    verify_directory(run_dir)


def test_export_refuses_changed_run_and_folders_inside_the_run(run_dir):
    run = load_run(run_dir)
    with pytest.raises(RunLoadError, match="Cannot create"):
        export_session(run, {}, run_dir / "exports")
    (run_dir / "cases" / "SYN-02" / "evidence.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RunLoadError, match="cannot be exported"):
        export_session(run, {}, run_dir.parent / "exports")


def test_resume_round_trip_and_rejections(tmp_path, run_dir, exports):
    run = load_run(run_dir)
    reviews = {"SYN-01": make_review(run["cases"][0], "Jeni", "Incorrect", "1", "Missing", "Fixed."),
               "SYN-02": make_review(run["cases"][1], "", "Pending", "Not counted", "Look again", "")}
    session = export_session(run, reviews, exports)
    assert list_exports(run, exports) == [session.name]
    assert import_session(run, session.name, exports) == reviews

    other = load_run(make_run(tmp_path / "runs" / "other-run", binding_prefix="b"))
    assert list_exports(other, exports) == []
    with pytest.raises(ReviewError, match="different case or response"):
        import_session(other, session.name, exports)

    repeated = exports / (session.name + "-repeated")
    repeated.mkdir()
    lines = (session / REVIEW_FILE).read_text(encoding="utf-8").splitlines()
    (repeated / REVIEW_FILE).write_text("\n".join(lines + lines[:1]) + "\n", encoding="utf-8")
    (repeated / CORRECTIONS_FILE).write_text((session / CORRECTIONS_FILE).read_text(encoding="utf-8"),
                                             encoding="utf-8")
    with pytest.raises(ReviewError, match="repeated"):
        import_session(run, repeated.name, exports)

    stale = exports / (session.name + "-stale")
    stale.mkdir()
    (stale / REVIEW_FILE).write_text((session / REVIEW_FILE).read_text(encoding="utf-8"), encoding="utf-8")
    corrections = json.loads((session / CORRECTIONS_FILE).read_text(encoding="utf-8"))
    corrections["run_seal_sha256"] = "0" * 64
    (stale / CORRECTIONS_FILE).write_text(json.dumps(corrections), encoding="utf-8")
    with pytest.raises(ReviewError, match="different or changed run"):
        import_session(run, stale.name, exports)

    for name in ["../x", "", None, "missing"]:
        with pytest.raises(ReviewError):
            import_session(run, name, exports)


def test_unsaved_edits_block_navigation_until_saved_or_discarded(run_dir):
    run = load_run(run_dir)
    assert on_form_edit(run, {}, "SYN-01", "Pending", "Not counted", "", "")[0] is False
    locked = on_form_edit(run, {}, "SYN-01", "Incorrect", "Not counted", "", "")
    assert locked[0] is True and "Unsaved changes" in locked[1]
    saved = {"SYN-01": make_review(run["cases"][0], "Jeni", "Incorrect", "1", "n", "s")}
    assert on_form_edit(run, saved, "SYN-01", "Incorrect", "1", "n", "s")[0] is False
    click = gr.SelectData(None, {"index": [1, 0], "value": "SYN-02", "row_value": ["SYN-02"],
                                 "col_value": [], "selected": True})
    assert on_table_select(False, click) == "SYN-02"
    assert on_table_select(True, click) != "SYN-02"
