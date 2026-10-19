"""Question-only examples for LIVE; never load reference answers or saved results."""

import json
from pathlib import Path
import re


CATALOG_PATH = Path(__file__).with_name("data") / "question_examples.json"
QUESTION_SETS = [("Custom question", "custom"),
                 ("Development (20)", "development"),
                 ("Evaluation (30)", "evaluation")]


def load_examples(path=CATALOG_PATH):
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("Question examples must be a list")
    by_id = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "case_id", "split", "question", "transcription_id"
        }:
            raise ValueError("Question examples may contain only question inputs and display labels")
        prefix = {"development": "DEV", "evaluation": "EVAL"}.get(row["split"])
        case_id, question, scope = row["case_id"], row["question"], row["transcription_id"]
        if (not prefix or not isinstance(case_id, str)
                or not re.fullmatch(rf"{prefix}-\d{{2}}", case_id)
                or case_id in by_id
                or not isinstance(question, str) or not question.strip() or len(question) > 2000
                or scope is not None and (type(scope) is not int or not 1 <= scope <= 2**63 - 1)):
            raise ValueError("Invalid question example or transcription scope")
        by_id[case_id] = row
    return by_id


EXAMPLES = load_examples()


def question_choices(split):
    if split not in {"custom", "development", "evaluation"}:
        raise ValueError("Choose Custom, Development or Evaluation")
    return [(f"{row['case_id']} — {row['question']}", row["case_id"])
            for row in EXAMPLES.values() if row["split"] == split]


def question_input(case_id, split):
    row = EXAMPLES.get(case_id)
    if row is None or row["split"] != split:
        raise ValueError("Choose a question from the selected set")
    return row["question"], "" if row["transcription_id"] is None else str(row["transcription_id"])
