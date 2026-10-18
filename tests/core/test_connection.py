import httpx
import pytest

from core.apertus import ApertusClient
from core.config import Settings
from core.service import answer_question, search_records


def test_private_default():
    assert Settings().base_url == "http://127.0.0.1:8010/v1"


@pytest.mark.parametrize("url", ["https://provider.invalid/v1", "http://127.0.0.1:8000/v1", "http://127.0.0.1:8010/not-v1"])
def test_rejects_external_or_track2_endpoint(url):
    with pytest.raises(ValueError):
        Settings(base_url=url)


def test_connection_smoke_with_explicit_wire_fixture():
    def handle(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": Settings().model}]})
        return httpx.Response(200, json={"model": Settings().model,
            "choices": [{"finish_reason": "stop", "message": {"content": "BERN_READY"}}]})
    client = ApertusClient(Settings(), transport=httpx.MockTransport(handle))
    try:
        result = client.smoke()
        assert result["connection_ok"] and result["exact_smoke_text"]
        assert not result["archive_question_answering_tested"]
    finally:
        client.close()


def test_wrong_served_model_is_rejected():
    client = ApertusClient(Settings(), transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"data": [{"id": "other"}]})))
    try:
        with pytest.raises(ValueError):
            client.models()
    finally:
        client.close()


@pytest.mark.parametrize("fn", [search_records, answer_question])
def test_unimplemented_archive_service_never_fakes_an_answer(fn):
    with pytest.raises(NotImplementedError):
        fn("Where is the school?")
