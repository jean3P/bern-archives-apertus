"""S5 saved-run review controls on small synthetic runs. No model, search or network calls."""

import json
import socket

import gradio as gr
import pytest

from core.evaluation_records import digest, seal_directory, verify_directory
from core.evaluation_scoring import load_reviews
from ui.review_records import (CORRECTIONS_FILE, REVIEW_FILE, ReviewError, RunLoadError, export_session,
                               discover_runs, import_session, list_exports, load_case_file, load_references, load_run,
                               make_review)
from ui.run_review import (evidence_html, is_technical_error, on_form_edit, on_load, on_table_select, question_answer_html,
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
        write(directory / "cases" / case_id / "binding_plan.json",
              {"synthetic": True, "requirements": [{"label": "place", "question_codes": ["I.1"]}]})
        (directory / "cases" / case_id / "events.jsonl").write_text(
            json.dumps({"event": "retrieval", "question_code": "I.1", "returned_record_ids": []}) + "\n",
            encoding="utf-8")
    (directory / "case-scores.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines),
                                                 encoding="utf-8")
    (directory / "references").mkdir()
    (directory / "references" / f"{split}-questions.jsonl").write_text(
        "".join(json.dumps(ref) + "\n" for ref in references), encoding="utf-8")
    # The evaluation set must never be opened by the dashboard; invalid JSON would fail if it were.
    other = "evaluation" if split == "development" else "development"
    (directory / "references" / f"{other}-questions.jsonl").write_text("NOT FOR THIS REVIEW\n", encoding="utf-8")
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


def test_evaluation_review_requires_opt_in_and_uses_its_own_reference_snapshot(tmp_path):
    directory = make_run(tmp_path / "evaluation-run", split="evaluation")
    before = inventory(directory)
    with pytest.raises(RunLoadError, match="Only development"):
        load_run(directory)
    with pytest.raises(RunLoadError, match="explicit review opt-in"):
        load_references(directory, "evaluation")
    run = load_run(directory, allow_evaluation=True)
    assert run["manifest"]["split"] == "evaluation"
    assert len(load_references(directory, "evaluation", allow_evaluation=True)) == 3
    loaded, shown, table, _, reviews = on_load(str(directory), allow_evaluation=True)
    assert len(loaded["references"]) == len(table) == 3 and reviews == {}
    assert "not an untouched test set" in shown
    assert inventory(directory) == before


def test_run_discovery_does_not_recurse_into_archives_or_reveal_evaluation_by_default(tmp_path):
    root = tmp_path / "runs"
    dev = make_run(root / "dev")
    evaluation = make_run(root / "evaluation", split="evaluation")
    make_run(root / "_archive" / "old")
    (root / "review-exports").mkdir()
    assert discover_runs(root) == [str(dev)]
    assert discover_runs(root, allow_evaluation=True) == [str(dev), str(evaluation)]
    assert discover_runs(root / "missing") == []


def test_bound_artifacts_are_available_without_opening_arbitrary_files(run_dir):
    artifact = load_case_file(run_dir, "SYN-01", "binding_plan.json")
    assert artifact["synthetic"] is True
    assert load_case_file(run_dir, "SYN-01", "binding_hold.json") is None
    with pytest.raises(RunLoadError):
        load_case_file(run_dir, "SYN-01", ".env")


def test_a_false_abstention_is_not_labelled_as_a_technical_error():
    case = {"observed_status": "insufficient_evidence", "attempted": True,
            "definitive_failure": True, "protocol_valid": True,
            "response_contract_valid": True}
    assert not is_technical_error(case)
    assert is_technical_error({**case, "protocol_valid": False})
    assert is_technical_error({**case, "observed_status": "error"})


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


def test_load_restores_latest_export_decisions_notes_and_suggestions(run_dir, exports):
    run = load_run(run_dir)
    original = inventory(run_dir)
    older = export_session(run, {}, exports)
    older.rename(exports / (run_dir.name + "-20260101T000000Z-00000001"))
    saved = {
        "SYN-01": make_review(run["cases"][0], "Jean", "Incorrect", "1", "Missing detail", "Fixed answer."),
        "SYN-02": make_review(run["cases"][1], "Jeni", "Correct", "0", "Supported abstention", ""),
        "SYN-03": make_review(run["cases"][2], "Jeni", "Incorrect", "0", "Technical failure", ""),
    }
    latest = export_session(run, saved, exports)
    latest = latest.rename(exports / (run_dir.name + "-20260102T000000Z-00000002"))
    loaded, shown, table, _, restored = on_load(str(run_dir), export_root=exports)
    assert restored == saved
    assert loaded["restored_export"] == latest.name
    assert "Restored saved reviews: 3 of 3" in shown and latest.name in shown
    assert [row[3] for row in table] == ["Incorrect", "Correct", "Incorrect"]
    from ui.run_review import on_show_form
    form = on_show_form(loaded, restored, "SYN-01")
    assert form[0] == "Incorrect" and form[2:4] == ("Missing detail", "Fixed answer.")
    assert inventory(run_dir) == original


def test_load_preserves_partial_reviews_without_inventing_decisions(run_dir, exports):
    run = load_run(run_dir)
    saved = {"SYN-01": make_review(run["cases"][0], "Jean", "Correct", "1", "Checked", "")}
    export_session(run, saved, exports)
    _, shown, table, _, restored = on_load(str(run_dir), export_root=exports)
    assert restored == saved and "Restored saved reviews: 1 of 3" in shown
    assert [row[3] for row in table] == ["Correct", "Pending", "Pending"]


def test_load_rejects_invalid_latest_review_instead_of_hiding_it(run_dir, exports):
    run = load_run(run_dir)
    valid = export_session(run, {}, exports)
    valid.rename(exports / (run_dir.name + "-20260101T000000Z-00000001"))
    invalid = export_session(run, {}, exports)
    invalid = invalid.rename(exports / (run_dir.name + "-20260102T000000Z-00000002"))
    records = [json.loads(line) for line in (invalid / REVIEW_FILE).read_text(encoding="utf-8").splitlines()]
    records[0]["review_binding"] = "0" * 64
    (invalid / REVIEW_FILE).write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")
    before = inventory(exports)
    loaded, shown, table, _, reviews = on_load(str(run_dir), export_root=exports)
    assert loaded is None and table == [] and reviews == {}
    assert "Could not load run or restore its latest saved review" in shown
    assert "no older export was silently substituted" in shown
    assert inventory(exports) == before


def test_load_without_export_explicitly_starts_new_pending_review(run_dir, exports):
    loaded, shown, table, _, reviews = on_load(str(run_dir), export_root=exports)
    assert loaded["restored_export"] is None and reviews == {}
    assert "No saved review export was found" in shown
    assert [row[3] for row in table] == ["Pending", "Pending", "Pending"]


def test_review_form_restores_each_decisions_author_without_rewriting_identity(run_dir):
    from ui.run_review import on_show_form, on_show_reviewer
    run = load_run(run_dir)
    reviews = {
        "SYN-01": make_review(run["cases"][0], "Jeni", "Correct", "1", "Checked", ""),
        "SYN-02": make_review(run["cases"][1], "Jean (user-authorized assistant amendment)",
                               "Correct", "0", "Amended", "Suggested wording"),
    }
    before = json.dumps(reviews, sort_keys=True)
    assert on_show_form(run, reviews, "SYN-01")[5] == "Jeni"
    assert on_show_form(run, reviews, "SYN-02")[5] == "Jean (user-authorized assistant amendment)"
    assert on_show_reviewer(run, reviews, "SYN-03") == "Not reviewed yet"
    assert on_show_form(None, {}, None)[5] == ""
    assert json.dumps(reviews, sort_keys=True) == before


def test_restored_author_is_read_only_and_separate_from_new_editors_name(run_dir):
    from ui.run_review import build_app
    app = build_app(str(run_dir), runs_root=run_dir.parent)
    config = app.get_config_file()
    by_label = {item.get("props", {}).get("label"): item for item in config["components"]}
    author = by_label["Reviewer of this decision"]
    editor = by_label["Your name (required only when saving an edit)"]
    assert author["props"]["interactive"] is False
    assert not editor["props"].get("value")
    form_outputs = [item["outputs"] for item in config["dependencies"]
                    if str(item.get("api_name", "")).startswith("show_form")]
    assert form_outputs and all(author["id"] in output for output in form_outputs)
    assert all(editor["id"] not in output for output in form_outputs)


def test_declared_institutions_follow_stored_author_without_rewriting_reviews(run_dir):
    from ui.run_review import on_show_form, on_show_identity
    run = load_run(run_dir)
    reviews = {
        "SYN-01": make_review(run["cases"][0], "Jeni", "Correct", "1", "Checked", ""),
        "SYN-02": make_review(run["cases"][1], "Jean (user-authorized assistant amendment)",
                               "Correct", "0", "Amended", "Suggested wording"),
        "SYN-03": make_review(run["cases"][2], "Jean", "Incorrect", "0", "Failure", ""),
    }
    before = json.dumps(reviews, sort_keys=True)
    assert on_show_identity(run, reviews, "SYN-01") == ("Jeni", "BFH — Berner Fachhochschule")
    assert on_show_form(run, reviews, "SYN-02")[5:] == (
        "Jean (user-authorized assistant amendment)", "University of Neuchâtel")
    assert on_show_form(run, reviews, "SYN-03")[5:] == ("Jean", "University of Neuchâtel")
    assert on_show_form(None, {}, None)[5:] == ("", "")
    assert json.dumps(reviews, sort_keys=True) == before


def test_unknown_reviewers_are_not_assigned_someone_elses_institution(run_dir):
    from ui.run_review import on_show_institution
    run = load_run(run_dir)
    assert on_show_institution(run, {}, "SYN-01") == "Not reviewed yet"
    assert on_show_institution(run, {"SYN-01": {"reviewer": "Jean Someone Else"}}, "SYN-01") == "Not specified"
    assert on_show_institution(None, {}, None) == ""


def test_institution_is_read_only_and_updates_with_form_and_save(run_dir):
    from ui.run_review import build_app
    app = build_app(str(run_dir), runs_root=run_dir.parent)
    config = app.get_config_file()
    by_label = {item.get("props", {}).get("label"): item for item in config["components"]}
    institution = by_label["Reviewer institution"]
    editor = by_label["Your name (required only when saving an edit)"]
    assert institution["props"]["interactive"] is False
    outputs = [item["outputs"] for item in config["dependencies"]
               if str(item.get("api_name", "")).startswith(("show_form", "on_show_identity"))]
    assert outputs and all(institution["id"] in output for output in outputs)
    assert all(editor["id"] not in output for output in outputs)


def test_saved_run_selector_contains_folder_names_not_paths(run_dir):
    from ui.run_review import build_app
    app = build_app(str(run_dir), runs_root=run_dir.parent)
    config = app.get_config_file()
    selector = next(c["props"] for c in config["components"] if c.get("props", {}).get("label") == "Saved run folder")
    assert [list(choice) for choice in selector["choices"]] == [[run_dir.name, run_dir.name]]
    assert selector["value"] == run_dir.name and selector["allow_custom_value"] is False
    assert str(run_dir.parent) not in json.dumps(selector)


def test_folder_name_loads_the_same_sealed_run_and_rejects_path_inputs(run_dir, monkeypatch):
    import ui.run_review as ui
    locations = {run_dir.name: str(run_dir)}
    calls = []
    sentinel = object()
    monkeypatch.setattr(ui, "on_load", lambda path, allow: calls.append((path, allow)) or sentinel)
    assert ui.on_load_folder(run_dir.name, locations, True) is sentinel
    assert calls == [(str(run_dir), True)]
    for value in (str(run_dir), "../syn-run", "unknown", None):
        run, message, table, _, reviews = ui.on_load_folder(value, locations, True)
        assert run is None and not table and not reviews
        assert "Choose a saved run folder" in message
    assert len(calls) == 1


def test_duplicate_folder_names_never_silently_select_a_different_run(run_dir, monkeypatch):
    import ui.run_review as ui
    monkeypatch.setattr(ui, "discover_runs", lambda *args, **kwargs: ["/first/same", "/second/same"])
    with pytest.raises(ValueError, match="distinct names"):
        ui.build_app(runs_root=run_dir.parent)
