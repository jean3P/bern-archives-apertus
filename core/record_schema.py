"""JSON Schema definitions and a validator for the exact subset emitted here."""

import re

from core.policy import SCHEMA_VERSION

TEXT = {"type": "string"}
NULLABLE_TEXT = {"type": ["string", "null"]}
ID = {"type": "integer", "minimum": 1}
NULLABLE_ID = {"type": ["integer", "null"], "minimum": 1}
IDS = {"type": "array", "items": ID, "uniqueItems": True}
FLAGS = {"type": "array", "items": TEXT, "uniqueItems": True}


def object_schema(properties):
    return {"type": "object", "additionalProperties": False,
            "required": list(properties), "properties": properties}


SOURCE = object_schema({
    "file_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
    "archive_member": TEXT, "table": TEXT, "row_id": ID, "column": TEXT,
})

SCHEMAS = {
    "documents": object_schema({
        "record_id": TEXT, "transcription_id": ID, "archive_reference": NULLABLE_TEXT,
        "archive_location": NULLABLE_TEXT, "header_original": NULLABLE_TEXT,
        "facsimile_filename": NULLABLE_TEXT, "release_status_source": TEXT,
        "multiple_schools_source": {"type": ["integer", "null"]},
        "school_ids": IDS, "answer_ids": IDS, "source": SOURCE,
    }),
    "questions": object_schema({
        "question_id": ID, "question_number": NULLABLE_TEXT,
        "text_original": NULLABLE_TEXT, "text_french": NULLABLE_TEXT,
    }),
    "answers": object_schema({
        "schema_version": {"const": SCHEMA_VERSION},
        "record_id": {"type": "string", "pattern": "^stapfer:answer:[0-9]+$"},
        "transcription_id": ID, "answer_id": ID, "question_id": ID,
        "question_number": NULLABLE_TEXT, "school_ids": IDS,
        "school_assignment_source_raw": {"type": ["integer", "null"]},
        "text_original": NULLABLE_TEXT, "text_search": NULLABLE_TEXT,
        "archive_reference": NULLABLE_TEXT, "facsimile_filename": NULLABLE_TEXT,
        "pdf_page_index": {"const": None}, "folio": {"const": None},
        "release_status_source": TEXT, "public_policy_version": TEXT,
        "evidence_layer": {"const": "scholarly_transcription"},
        "source": SOURCE, "quality_flags": FLAGS,
    }),
    "schools": object_schema({
        "school_id": ID, "transcription_id": ID, "place_id": NULLABLE_ID,
        "name_original": NULLABLE_TEXT,
    }),
    "places": object_schema({
        "place_id": ID, "name_original": NULLABLE_TEXT,
        "canton_1799": NULLABLE_TEXT, "canton_1780": NULLABLE_TEXT,
        "canton_edition_current": NULLABLE_TEXT,
    }),
    "teachers": object_schema({
        "teacher_id": ID, "family_name_original": NULLABLE_TEXT,
        "given_name_original": NULLABLE_TEXT, "origin_original": NULLABLE_TEXT,
    }),
    "school_teachers": object_schema({"school_id": ID, "teacher_id": ID}),
}


def validate(value, schema, path="record"):
    """Implements types/const/required/properties/items/pattern/minimum/uniqueness."""
    if "const" in schema and value != schema["const"]:
        raise ValueError(path + ": wrong constant")
    expected = schema.get("type")
    types = expected if isinstance(expected, list) else [expected] if expected else []
    kinds = {"object": type(value) is dict, "array": type(value) is list,
             "string": type(value) is str, "integer": type(value) is int, "null": value is None}
    if types and not any(kinds[kind] for kind in types):
        raise ValueError(path + ": wrong type")
    if value is None:
        return
    if "minimum" in schema and value < schema["minimum"]:
        raise ValueError(path + ": below minimum")
    if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
        raise ValueError(path + ": invalid identifier")
    if expected == "object":
        properties = schema["properties"]
        if set(value) != set(properties):
            raise ValueError(path + ": missing or unexpected fields")
        for key, definition in properties.items():
            validate(value[key], definition, path + "." + key)
    if expected == "array":
        for index, item in enumerate(value):
            validate(item, schema["items"], path + "[" + str(index) + "]")
        if schema.get("uniqueItems") and len(value) != len(set(value)):
            raise ValueError(path + ": duplicate items")


def export_schema():
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "Local Stapfer J2 record definitions",
            "description": "Project schema, not an official organizer interchange standard.",
            "$defs": SCHEMAS}
