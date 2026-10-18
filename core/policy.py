"""Explicit J2 projection of the pinned scholarly edition, not a publishing action."""

SQL_SHA256 = "68eba6c4a7cc13eb3e0b6239b00a6ee21e2e0996a24de69224c3915480941c97"
SQL_MEMBER = "stapferappdb_final_10.5.16.sql"
POLICY_VERSION = "stapfer-internet-allowlist-v1"
SCHEMA_VERSION = "j2-v1"
PUBLIC_STATUS = "Internet"  # Exact observed source label; other values remain excluded.
SOURCE_URL = "https://sfa-laboratory.ch/Hackathon/Stapfer/stapferappdb_final.sql.zip"
SOURCE_TERMS = "https://opendata.swiss/terms-of-use#terms_open"

PUBLIC_FIELDS = {
    "t_transkription": (
        "id_transkription", "transkription_quelle_signatur", "transkription_quelle_standort",
        "transkription_briefkopf", "transkription_faksimile_quelle",
        "transkription_freigabestatus", "transkription_mehrere_schulen",
    ),
    "t_antwort": ("id_antwort", "antwort", "f_id_frage", "f_id_transkription", "antwort_zugehoerig"),
    "t_frage": ("id_frage", "frage", "frage_nummer", "frage_f"),
    "t_schule": ("id_schule", "schule_name", "f_id_transkription", "f_id_ort"),
    "t_ort": ("id_ort", "ort_name", "ort_kanton_1799", "ort_kanton_1780", "ort_kanton_aktuell"),
    "t_lehrer": ("id_lehrer", "lehrer_name", "lehrer_vorname", "lehrer_herkunft"),
    "r_lehrer_schule": ("f_id_lehrer", "f_id_schule"),
}

EXPECTED_ROWS = {
    "t_transkription": 2250, "t_antwort": 92524, "t_frage": 60,
    "t_schule": 3229, "t_ort": 2143, "t_lehrer": 2443, "r_lehrer_schule": 3217,
}


def public_policy():
    return {
        "version": POLICY_VERSION, "allowed_release_statuses": [PUBLIC_STATUS],
        "source_columns": {table: list(columns) for table, columns in PUBLIC_FIELDS.items()},
        "excluded": ["modern contributors", "internal/public editorial comments", "administration",
                     "binary SSMA_TimeStamp", "all unlisted columns/tables"],
        "school_links": "transcription context, not attribution of each answer to each school",
        "antwort_zugehoerig": "preserved as an uninterpreted integer; no school assignment inferred",
        "original_text": "faithful SQL string decoding; no modernization or marker removal",
        "search_text": "Unicode NFC and collapsed whitespace only",
        "release_review": "Internet is the sole admitted source label; unknown labels are excluded",
        "publication": "local projection only; no automatic upload or independent privacy certification",
    }
