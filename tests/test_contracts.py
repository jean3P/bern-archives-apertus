import copy
import json
from pathlib import Path

import pytest

from contracts import validate_response

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/ui"


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.json")))
def test_display_examples_are_valid_and_explicitly_demo(path):
    value = json.loads(path.read_text(encoding="utf-8"))
    validate_response(value)
    assert value["mode"] == "demo"


def test_nonanswer_cannot_retain_stale_answer():
    value = json.loads((FIXTURES / "error.demo.json").read_text(encoding="utf-8"))
    value["answer"] = "A stale answer"
    with pytest.raises(ValueError):
        validate_response(value)


def test_bad_page_index_is_rejected():
    value = json.loads((FIXTURES / "answered.demo.json").read_text(encoding="utf-8"))
    value = copy.deepcopy(value)
    value["sources"][0]["pdf_page_index"] = -1
    with pytest.raises(ValueError):
        validate_response(value)
