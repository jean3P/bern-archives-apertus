"""Deterministic public projection. No model, inferred identity or source edits."""

from collections import Counter, defaultdict
import hashlib
import re
import unicodedata

from core.policy import POLICY_VERSION, PUBLIC_STATUS, SCHEMA_VERSION
from core.record_schema import SCHEMAS, validate


def normalize_search(text):
    return None if text is None else re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def text_hash(text):
    return None if text is None else hashlib.sha256(text.encode("utf-8")).hexdigest()


def keyed(rows, key):
    result = {}
    for row in rows:
        value = row[key]
        if type(value) is not int or value < 1 or value in result:
            raise ValueError("Invalid or duplicate source primary key: " + key)
        result[value] = row
    return result


def project(dump, transcription_id=None):
    tables = dump.tables
    trans = keyed(tables["t_transkription"], "id_transkription")
    raw_answers = keyed(tables["t_antwort"], "id_antwort")
    questions = keyed(tables["t_frage"], "id_frage")
    schools = keyed(tables["t_schule"], "id_schule")
    places = keyed(tables["t_ort"], "id_ort")
    teachers = keyed(tables["t_lehrer"], "id_lehrer")
    eligible = {key: row for key, row in trans.items()
                if row["transkription_freigabestatus"] == PUBLIC_STATUS}
    if transcription_id is not None and transcription_id not in eligible:
        raise ValueError("Requested transcription is missing or not admitted by the public policy")
    selected = eligible if transcription_id is None else {transcription_id: eligible[transcription_id]}
    rows = {name: [] for name in SCHEMAS}
    excluded = {name: Counter() for name in ("documents", "answers", "schools", "school_teachers")}
    excluded["documents"]["release_status_not_admitted"] = len(trans) - len(eligible)
    excluded["documents"]["outside_requested_scope"] = len(eligible) - len(selected)
    doc_schools, admitted_schools = defaultdict(list), set()
    needed_places, needed_teachers = set(), set()
    for key, source in sorted(schools.items()):
        if source["f_id_transkription"] not in selected:
            excluded["schools"]["outside_selected_public_documents"] += 1
            continue
        place = source["f_id_ort"]
        if place is not None and place not in places:
            excluded["schools"]["dangling_place_reference"] += 1
            continue
        rows["schools"].append({"school_id": key, "transcription_id": source["f_id_transkription"],
                                "place_id": place, "name_original": source["schule_name"]})
        doc_schools[source["f_id_transkription"]].append(key)
        admitted_schools.add(key)
        if place is not None:
            needed_places.add(place)
    seen_relations = set()
    for source in tables["r_lehrer_schule"]:
        school, teacher = source["f_id_schule"], source["f_id_lehrer"]
        if school not in admitted_schools:
            excluded["school_teachers"]["outside_admitted_schools"] += 1
        elif teacher not in teachers:
            excluded["school_teachers"]["dangling_teacher_reference"] += 1
        elif (school, teacher) in seen_relations:
            excluded["school_teachers"]["duplicate_relation"] += 1
        else:
            seen_relations.add((school, teacher))
            needed_teachers.add(teacher)
            rows["school_teachers"].append({"school_id": school, "teacher_id": teacher})
    rows["school_teachers"].sort(key=lambda row: (row["school_id"], row["teacher_id"]))
    for key in sorted(needed_places):
        source = places[key]
        rows["places"].append({"place_id": key, "name_original": source["ort_name"],
            "canton_1799": source["ort_kanton_1799"], "canton_1780": source["ort_kanton_1780"],
            "canton_edition_current": source["ort_kanton_aktuell"]})
    for key in sorted(needed_teachers):
        source = teachers[key]
        rows["teachers"].append({"teacher_id": key, "family_name_original": source["lehrer_name"],
            "given_name_original": source["lehrer_vorname"], "origin_original": source["lehrer_herkunft"]})
    for key, source in sorted(questions.items()):
        rows["questions"].append({"question_id": key, "question_number": source["frage_nummer"],
                                 "text_original": source["frage"], "text_french": source["frage_f"]})
    doc_answers, transformations, flags = defaultdict(list), [], Counter()

    def locator(table, key, column):
        return {"file_sha256": dump.sha256, "archive_member": dump.member,
                "table": table, "row_id": key, "column": column}

    for key, source in sorted(raw_answers.items()):
        doc, question = source["f_id_transkription"], source["f_id_frage"]
        if doc not in trans:
            excluded["answers"]["missing_transcription_reference"] += 1
            continue
        if doc not in selected:
            excluded["answers"]["outside_selected_public_documents"] += 1
            continue
        if question not in questions:
            excluded["answers"]["missing_question_reference"] += 1
            continue
        document = trans[doc]
        original = source["antwort"]
        search = normalize_search(original)
        quality = ["school_links_are_transcription_context_not_answer_attribution"]
        if original is None:
            quality.append("null_original_text")
        elif not search:
            quality.append("blank_original_text")
        if not doc_schools[doc]:
            quality.append("no_admitted_school_context")
        if not document["transkription_quelle_signatur"]:
            quality.append("missing_archive_reference")
        if source["antwort_zugehoerig"] is not None:
            quality.append("uninterpreted_school_assignment")
        row = {"schema_version": SCHEMA_VERSION, "record_id": "stapfer:answer:" + str(key),
            "transcription_id": doc, "answer_id": key, "question_id": question,
            "question_number": questions[question]["frage_nummer"], "school_ids": sorted(doc_schools[doc]),
            "school_assignment_source_raw": source["antwort_zugehoerig"],
            "text_original": original, "text_search": search,
            "archive_reference": document["transkription_quelle_signatur"],
            "facsimile_filename": document["transkription_faksimile_quelle"],
            "pdf_page_index": None, "folio": None,
            "release_status_source": document["transkription_freigabestatus"],
            "public_policy_version": POLICY_VERSION, "evidence_layer": "scholarly_transcription",
            "source": locator("t_antwort", key, "antwort"), "quality_flags": quality}
        rows["answers"].append(row)
        doc_answers[doc].append(key)
        flags.update(quality)
        transformations.append({"record_id": row["record_id"], "source_field": "text_original",
            "derived_field": "text_search", "rule": "unicode-nfc-collapse-whitespace-v1",
            "original_sha256": text_hash(original), "search_sha256": text_hash(search),
            "changed": original != search, "original_modified": False})
    for key, source in sorted(selected.items()):
        rows["documents"].append({"record_id": "stapfer:transcription:" + str(key),
            "transcription_id": key, "archive_reference": source["transkription_quelle_signatur"],
            "archive_location": source["transkription_quelle_standort"],
            "header_original": source["transkription_briefkopf"],
            "facsimile_filename": source["transkription_faksimile_quelle"],
            "release_status_source": source["transkription_freigabestatus"],
            "multiple_schools_source": source["transkription_mehrere_schulen"],
            "school_ids": sorted(doc_schools[key]), "answer_ids": sorted(doc_answers[key]),
            "source": locator("t_transkription", key, "transkription_quelle_signatur")})
    for name, records in rows.items():
        for record in records:
            validate(record, SCHEMAS[name], name)
    report = {"scope": "all_eligible" if transcription_id is None else "one_transcription",
        "selected_transcription_id": transcription_id, "raw_table_counts": dump.counts,
        "release_status_counts": dict(Counter(row["transkription_freigabestatus"]
                                              if row["transkription_freigabestatus"] is not None
                                              else "<NULL>" for row in trans.values())),
        "eligible_transcriptions_before_scope": len(eligible),
        "exported_counts": {name: len(records) for name, records in rows.items()},
        "excluded_counts": {name: dict(counts) for name, counts in excluded.items()},
        "answer_quality_flags": dict(flags),
        "raw_relationship_issues": {
            "answer_missing_transcription": sum(row["f_id_transkription"] not in trans for row in raw_answers.values()),
            "answer_missing_question": sum(row["f_id_frage"] not in questions for row in raw_answers.values()),
            "school_missing_transcription": sum(row["f_id_transkription"] not in trans for row in schools.values()),
            "school_null_place": sum(row["f_id_ort"] is None for row in schools.values()),
            "school_dangling_place": sum(row["f_id_ort"] is not None and row["f_id_ort"] not in places for row in schools.values()),
            "teacher_link_missing_school": sum(row["f_id_schule"] not in schools for row in tables["r_lehrer_schule"]),
            "teacher_link_missing_teacher": sum(row["f_id_lehrer"] not in teachers for row in tables["r_lehrer_schule"]),
        },
        "indexable_answers": sum(bool(row["text_search"]) for row in rows["answers"]),
        "raw_text_roundtrip_checked": False, "model_calls": 0, "source_sql_executed": False}
    if len(rows["answers"]) + sum(excluded["answers"].values()) != len(raw_answers):
        raise ValueError("Answer coverage does not reconcile")
    return rows, transformations, report
