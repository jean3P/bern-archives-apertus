"""Synthetic software controls only. No real dump, model server or network access."""

import hashlib
import json

import pytest

from core.dataset import normalize_search, project
from core.dataset_cli import build, verify
from core.policy import PUBLIC_FIELDS, SQL_MEMBER, SQL_SHA256
from core.search import build_index, lookup_source, search_records
from core.sql_dump import Dump, literal, parse_dump, read_dump, statements, value_rows


@pytest.mark.parametrize(("token", "expected"), [
    ("NULL", None), ("0", 0), ("''", ""), ("'NULL'", "NULL"),
    (r"'a\nb\tc'", "a\nb\tc"), (r"'a\'b'", "a'b"),
    ("'a''b'", "a'b"), (r"'C:\\data'", "C:\\data"),
    (r"'\%\_'", r"\%\_"), ("'Hörndli $ $$ @ @@'", "Hörndli $ $$ @ @@"),
    ("b'1'", 1), ("0x00ff", bytes([0, 255])),
])
def test_mysql_scalars(token, expected):
    assert literal(token) == expected


def test_statements_do_not_split_or_interpret_quoted_instructions():
    source = "-- comment\nINSERT INTO `x` VALUES (1,'a; INSERT INTO `private` VALUES (2); -- data'); /* ignored */ SET x=1;"
    parsed = list(statements(source))
    assert len(parsed) == 2
    assert "private" in parsed[0]
    assert parsed[1] == "SET x=1"


def test_value_rows_handle_punctuation_and_doubled_quotes():
    rows = list(value_rows("(1,'a,b;()'),(2,'it''s fine')"))
    assert [[literal(token) for token in row] for row in rows] == [[1, "a,b;()"], [2, "it's fine"]]


@pytest.mark.parametrize("source", ["(1,'unterminated)", "(1),", "(1,concat('a','b'))", "(1) garbage"])
def test_unsupported_or_truncated_values_fail(source):
    with pytest.raises(ValueError):
        list(value_rows(source))


def test_public_column_reader_excludes_internal_fields_and_handles_binary():
    sql = """CREATE TABLE `x` (
      `id` int,
      `text` text,
      `internal` text,
      `SSMA_TimeStamp` blob
    );
    INSERT INTO `x` VALUES (1,'keep $','DO_NOT_EXPORT','\udcff');
    """
    tables, _, counts = parse_dump(sql, projection={"x": ("id", "text")})
    assert tables == {"x": [{"id": 1, "text": "keep $"}]}
    assert counts == {"x": 1}


def test_invalid_utf8_in_public_text_fails_instead_of_replacing():
    sql = "CREATE TABLE `x` (\n`id` int,\n`text` text\n); INSERT INTO `x` VALUES (1,'\udcff');"
    with pytest.raises(UnicodeError):
        parse_dump(sql, projection={"x": ("id", "text")})


def test_mysqldump_plural_lock_controls_are_recognized_without_execution():
    sql = """CREATE TABLE `x` (
      `id` int,
      `text` text
    );
    LOCK TABLES `x` WRITE;
    INSERT INTO `x` VALUES (1,'original; $ $$');
    UNLOCK TABLES;
    """
    tables, _, counts = parse_dump(sql, projection={"x": ("id", "text")})
    assert tables == {"x": [{"id": 1, "text": "original; $ $$"}]}
    assert counts == {"x": 1}


def test_lock_of_undefined_table_is_not_silently_skipped():
    with pytest.raises(ValueError, match="undefined table"):
        parse_dump("LOCK TABLES `missing` WRITE;", projection={})


def test_unknown_data_mutation_still_fails_without_logging_its_values():
    with pytest.raises(ValueError, match=r"statement 1 \(UPDATE\)") as error:
        parse_dump("UPDATE `x` SET text='PRIVATE_SENTINEL';", projection={})
    assert "PRIVATE_SENTINEL" not in str(error.value)


def test_source_hash_mismatch_fails_before_zip_or_sql_processing(tmp_path):
    source = tmp_path / "not-the-source.zip"
    source.write_bytes(b"not a zip")
    with pytest.raises(ValueError, match="pinned source"):
        read_dump(source)


@pytest.fixture
def synthetic_dump():
    def row(table, **values):
        return dict.fromkeys(PUBLIC_FIELDS[table]) | values
    tables = {name: [] for name in PUBLIC_FIELDS}
    tables["t_transkription"] = [
        row("t_transkription", id_transkription=16, transkription_freigabestatus="Internet",
            transkription_quelle_signatur="SYNTHETIC ARCHIVE", transkription_mehrere_schulen=1),
        row("t_transkription", id_transkription=17, transkription_freigabestatus="Unknown"),
    ]
    tables["t_frage"] = [row("t_frage", id_frage=1, frage="Location", frage_nummer="I.1", frage_f="Lieu")]
    tables["t_antwort"] = [
        row("t_antwort", id_antwort=41, antwort="Hörndli, OR $\n $$ @ @@", f_id_frage=1, f_id_transkription=16),
        row("t_antwort", id_antwort=42, antwort=None, f_id_frage=1, f_id_transkription=16),
        row("t_antwort", id_antwort=43, antwort="NONPUBLIC_SENTINEL", f_id_frage=1, f_id_transkription=17),
        row("t_antwort", id_antwort=44, antwort="Bad question", f_id_frage=999, f_id_transkription=16),
        row("t_antwort", id_antwort=45, antwort="Orphan", f_id_frage=1, f_id_transkription=999),
    ]
    tables["t_schule"] = [row("t_schule", id_schule=key, schule_name="School", f_id_transkription=16,
                              f_id_ort=62) for key in (24, 25)]
    tables["t_ort"] = [row("t_ort", id_ort=62, ort_name="Hörnli", ort_kanton_1799="Zürich",
                           ort_kanton_1780="Zürich", ort_kanton_aktuell="Different canton")]
    tables["t_lehrer"] = [row("t_lehrer", id_lehrer=130, lehrer_name="Historical teacher")]
    tables["r_lehrer_schule"] = [row("r_lehrer_schule", f_id_lehrer=130, f_id_schule=24)]
    return Dump(tables, {}, {name: len(values) for name, values in tables.items()}, SQL_SHA256, SQL_MEMBER)


def test_projection_preserves_nulls_ids_and_context_without_answer_fanout(synthetic_dump):
    rows, changes, report = project(synthetic_dump)
    assert [row["answer_id"] for row in rows["answers"]] == [41, 42]
    assert rows["answers"][0]["school_ids"] == [24, 25]
    assert rows["answers"][1]["text_original"] is None
    assert rows["answers"][0]["pdf_page_index"] is None
    assert rows["answers"][0]["text_original"] == synthetic_dump.tables["t_antwort"][0]["antwort"]
    assert "NONPUBLIC_SENTINEL" not in json.dumps(rows)
    assert all(not change["original_modified"] for change in changes)
    assert report["indexable_answers"] == 1
    assert sum(report["excluded_counts"]["answers"].values()) + len(rows["answers"]) == 5


def test_nonpublic_scope_is_not_overridden(synthetic_dump):
    with pytest.raises(ValueError, match="not admitted"):
        project(synthetic_dump, 17)


def test_duplicate_source_id_fails(synthetic_dump):
    synthetic_dump.tables["t_antwort"].append(dict(synthetic_dump.tables["t_antwort"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        project(synthetic_dump)


def test_search_normalization_keeps_markers_and_original_separate():
    original = "Ho\u0308rndli\n $ $$ @ @@  "
    assert normalize_search(original) == "Hörndli $ $$ @ @@"
    assert original.endswith("  ")


@pytest.fixture
def synthetic_index(tmp_path, synthetic_dump):
    rows, _, _ = project(synthetic_dump)
    build_index(tmp_path / "search.sqlite3", rows, SQL_SHA256)
    # A test-only software receipt, not evidence of a real data acquisition/import.
    digest = hashlib.sha256((tmp_path / "search.sqlite3").read_bytes()).hexdigest()
    (tmp_path / "_SUCCESS.json").write_text(json.dumps({"source_sha256": SQL_SHA256,
        "status": "completed", "artifact_sha256": {"search.sqlite3": digest}}), encoding="utf-8")
    return tmp_path


def test_search_and_exact_lookup_return_original_sources_once(synthetic_index):
    results = search_records("Hörndli", 16, data_dir=synthetic_index)
    assert len(results) == 1
    assert results[0]["record_id"] == "stapfer:answer:41"
    assert results[0]["text_original"] == "Hörndli, OR $\n $$ @ @@"
    assert lookup_source("stapfer:answer:41", data_dir=synthetic_index) == results[0]


def test_filters_use_historical_canton_and_preserve_no_results(synthetic_index):
    assert len(search_records("Hörndli", place="Hörnli", canton_1799="Zürich", question_code="I.1",
                              data_dir=synthetic_index)) == 1
    assert search_records("Hörndli", canton_1799="Different canton", data_dir=synthetic_index) == []
    assert search_records("missingterm", data_dir=synthetic_index) == []
    assert search_records("OR", data_dir=synthetic_index)[0]["record_id"] == "stapfer:answer:41"
    assert search_records("'; DROP TABLE answers; --", data_dir=synthetic_index) == []
    assert lookup_source("stapfer:answer:41", data_dir=synthetic_index)


def test_absent_completion_marker_blocks_search(tmp_path):
    with pytest.raises(FileNotFoundError):
        search_records("Hörndli", data_dir=tmp_path)


def test_existing_output_directory_is_never_overwritten(tmp_path):
    source = tmp_path / "raw" / "absent.zip"
    source.parent.mkdir()
    output = tmp_path / "existing"
    output.mkdir()
    (output / "keep.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        build(source, output)
    assert (output / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_output_inside_raw_directory_is_rejected_before_creation(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    output = raw / "derived"
    with pytest.raises(ValueError, match="raw input directory"):
        build(raw / "absent.zip", output)
    assert not output.exists()


def test_full_orchestration_with_explicit_software_source_double(tmp_path, synthetic_dump, monkeypatch):
    import core.dataset_cli as dataset_cli
    source = tmp_path / "raw" / "software-source.zip"
    source.parent.mkdir()
    source.write_bytes(b"SOFTWARE FIXTURE, NOT THE ACTUAL SOURCE")
    original_hash = dataset_cli.file_hash
    monkeypatch.setattr(dataset_cli, "read_dump", lambda path: synthetic_dump)
    monkeypatch.setattr(dataset_cli, "file_hash", lambda path: SQL_SHA256 if path == source.resolve() else original_hash(path))
    output = tmp_path / "derived" / "fixture"
    report = build(source, output, 16)
    assert report["status"] == "validated"
    assert verify(output)["answer_text_roundtrips"] == 2
    assert (output / "_SUCCESS.json").is_file()
    assert "NONPUBLIC_SENTINEL" not in (output / "answers.jsonl").read_text(encoding="utf-8")
    (output / "answers.jsonl").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="Changed/missing"):
        verify(output)
