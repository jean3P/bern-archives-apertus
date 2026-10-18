"""CPU-only SQLite FTS5 search over a completed, explicit public projection."""

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import unicodedata

from dotenv import load_dotenv

from contracts import SourceCard
from core.config import ROOT
from core.policy import SCHEMA_VERSION, SQL_SHA256


def configured_data_dir():
    load_dotenv(ROOT / ".env", override=False)
    value = Path(os.getenv("BERN_DATA_DIR", "data/derived/j2-full"))
    return value if value.is_absolute() else ROOT / value


def json_text(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def build_index(path, records, source_sha256):
    if path.exists():
        raise FileExistsError("Refusing to overwrite an existing search database")
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript("""
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE documents (id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE questions (id INTEGER PRIMARY KEY, code TEXT, payload TEXT NOT NULL);
            CREATE TABLE places (id INTEGER PRIMARY KEY, name_fold TEXT, canton_1799_fold TEXT, payload TEXT NOT NULL);
            CREATE TABLE schools (id INTEGER PRIMARY KEY,
                transcription_id INTEGER NOT NULL REFERENCES documents(id),
                place_id INTEGER REFERENCES places(id), payload TEXT NOT NULL);
            CREATE TABLE teachers (id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE school_teachers (school_id INTEGER REFERENCES schools(id),
                teacher_id INTEGER REFERENCES teachers(id), PRIMARY KEY(school_id, teacher_id));
            CREATE TABLE answers (id INTEGER PRIMARY KEY, record_id TEXT NOT NULL UNIQUE,
                transcription_id INTEGER NOT NULL REFERENCES documents(id),
                question_id INTEGER NOT NULL REFERENCES questions(id),
                text_original TEXT, text_search TEXT, payload TEXT NOT NULL);
            CREATE INDEX answers_document ON answers(transcription_id);
            CREATE INDEX schools_document ON schools(transcription_id);
            CREATE INDEX schools_place ON schools(place_id);
            CREATE VIRTUAL TABLE answers_fts USING fts5(text_search, question_text, place_text,
                tokenize='unicode61 remove_diacritics 2');
        """)
        with connection:
            connection.executemany("INSERT INTO metadata VALUES (?, ?)",
                                   [("source_sha256", source_sha256), ("schema_version", SCHEMA_VERSION)])
            connection.executemany("INSERT INTO documents VALUES (?, ?)",
                [(row["transcription_id"], json_text(row)) for row in records["documents"]])
            connection.executemany("INSERT INTO questions VALUES (?, ?, ?)",
                [(row["question_id"], row["question_number"], json_text(row)) for row in records["questions"]])
            connection.executemany("INSERT INTO places VALUES (?, ?, ?, ?)",
                [(row["place_id"], (row["name_original"] or "").casefold(),
                  (row["canton_1799"] or "").casefold(), json_text(row)) for row in records["places"]])
            connection.executemany("INSERT INTO schools VALUES (?, ?, ?, ?)",
                [(row["school_id"], row["transcription_id"], row["place_id"], json_text(row))
                 for row in records["schools"]])
            connection.executemany("INSERT INTO teachers VALUES (?, ?)",
                [(row["teacher_id"], json_text(row)) for row in records["teachers"]])
            connection.executemany("INSERT INTO school_teachers VALUES (?, ?)",
                [(row["school_id"], row["teacher_id"]) for row in records["school_teachers"]])
            questions = {row["question_id"]: row for row in records["questions"]}
            places = {row["place_id"]: row for row in records["places"]}
            context = {}
            for school in records["schools"]:
                place = places.get(school["place_id"], {})
                context.setdefault(school["transcription_id"], []).extend([
                    school["name_original"] or "", place.get("name_original") or "",
                    place.get("canton_1799") or ""])
            for row in records["answers"]:
                connection.execute("INSERT INTO answers VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (row["answer_id"], row["record_id"], row["transcription_id"], row["question_id"],
                     row["text_original"], row["text_search"], json_text(row)))
                if row["text_search"]:
                    question = questions[row["question_id"]]
                    connection.execute("INSERT INTO answers_fts(rowid, text_search, question_text, place_text) VALUES (?, ?, ?, ?)",
                        (row["answer_id"], row["text_search"],
                         "\n".join([question["text_original"] or "", question["text_french"] or ""]),
                         "\n".join(context.get(row["transcription_id"], []))))
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("SQLite foreign-key check failed")


def open_index(data_dir):
    directory = Path(data_dir).resolve()
    marker = directory / "_SUCCESS.json"
    database = directory / "search.sqlite3"
    if not marker.is_file() or not database.is_file():
        raise FileNotFoundError("J2 dataset is not ready; run the build command first")
    receipt = json.loads(marker.read_text(encoding="utf-8"))
    if receipt.get("status") != "completed" or receipt.get("source_sha256") != SQL_SHA256:
        raise ValueError("Dataset completion receipt has the wrong status/source")
    with database.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != receipt.get("artifact_sha256", {}).get("search.sqlite3"):
            raise ValueError("Search database differs from the completed build; run verify")
    connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    try:
        metadata = dict(connection.execute("SELECT key, value FROM metadata"))
        if metadata != {"source_sha256": receipt["source_sha256"], "schema_version": SCHEMA_VERSION}:
            raise ValueError("Dataset/index metadata differ")
        connection.execute("PRAGMA query_only=ON")
    except Exception:
        connection.close()
        raise
    return connection


def source_card(record) -> SourceCard:
    return {key: record[key] for key in SourceCard.__annotations__}


def lookup_source(record_id, *, data_dir=None):
    if not re.fullmatch(r"stapfer:answer:[1-9][0-9]*", record_id):
        raise ValueError("Expected a Stapfer answer record ID")
    with closing(open_index(data_dir or configured_data_dir())) as connection:
        found = connection.execute("SELECT payload, text_search FROM answers WHERE record_id=?", (record_id,)).fetchone()
    if found is None:
        raise LookupError("Source record is not in this public dataset")
    if not found[1]:
        raise LookupError("Source exists but has no nonblank passage")
    return source_card(json.loads(found[0]))


def search_records(query, transcription_id=None, *, place=None, canton_1799=None,
                   question_code=None, limit=20, data_dir=None):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if transcription_id is not None and (type(transcription_id) is not int or transcription_id < 1):
        raise ValueError("transcription_id must be a positive integer")
    if not isinstance(query, str) or len(query) > 2000:
        raise ValueError("Query must be text of at most 2000 characters")
    terms = re.findall(r"[^\W_]+", unicodedata.normalize("NFC", query), flags=re.UNICODE)
    if len(terms) > 32:
        raise ValueError("Use at most 32 search terms")
    if not terms and (query.strip() or not any([transcription_id, place, canton_1799, question_code])):
        return []
    filters, values = ["a.text_search IS NOT NULL", "a.text_search != ''"], []
    source = "answers a JOIN questions q ON q.id=a.question_id"
    order = "a.id"
    if terms:
        source += " JOIN answers_fts ON answers_fts.rowid=a.id"
        filters.append("answers_fts MATCH ?")
        values.append(" AND ".join('"' + term + '"' for term in terms))
        order = "bm25(answers_fts), a.id"
    if transcription_id is not None:
        filters.append("a.transcription_id=?")
        values.append(transcription_id)
    if question_code is not None:
        filters.append("q.code = ? COLLATE NOCASE")
        values.append(question_code.strip())
    if place is not None or canton_1799 is not None:
        where = ["s.transcription_id=a.transcription_id"]
        if place is not None:
            where.append("p.name_fold=?")
            values.append(place.strip().casefold())
        if canton_1799 is not None:
            where.append("p.canton_1799_fold=?")
            values.append(canton_1799.strip().casefold())
        filters.append("EXISTS (SELECT 1 FROM schools s JOIN places p ON p.id=s.place_id WHERE " + " AND ".join(where) + ")")
    sql = "SELECT a.payload FROM " + source + " WHERE " + " AND ".join(filters) + " ORDER BY " + order + " LIMIT ?"
    with closing(open_index(data_dir or configured_data_dir())) as connection:
        found = connection.execute(sql, values + [limit]).fetchall()
    return [source_card(json.loads(row[0])) for row in found]
