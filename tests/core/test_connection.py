import httpx
import pytest

from core.apertus import ApertusClient
from core.config import Settings
from core.service import answer_question, search_records


def test_private_default():
    assert Settings().base_url == "http://127.0.0.1:8010/v1"


@pytest.mark.parametrize("url", ["https://provider.invalid/v1", "http://127.0.0.1:8000/v1", "http://model-server.local:9000/v1"])
def test_accepts_local_and_remote_model_servers(url):
    assert Settings(base_url=url).base_url == url


@pytest.mark.parametrize("url", ["file:///v1", "http:///v1", "http://localhost:8010/not-v1", "https://user:secret@provider.invalid/v1", "https://provider.invalid/v1?key=secret", "http://localhost:0/v1"])
def test_rejects_invalid_or_credential_bearing_urls(url):
    with pytest.raises(ValueError):
        Settings(base_url=url)


def test_optional_api_key_is_sent_but_not_exposed_in_settings_repr():
    config = Settings(base_url="https://provider.invalid/v1", api_key="test-only-key")
    def handle(request):
        assert request.headers["Authorization"] == "Bearer test-only-key"
        return httpx.Response(200, json={"data": [{"id": config.model}]})
    client = ApertusClient(config, transport=httpx.MockTransport(handle))
    try:
        assert client.models()["data"][0]["id"] == config.model
        assert "test-only-key" not in repr(config)
    finally:
        client.close()


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


def test_archive_service_delegates_without_changing_the_ui_contract(monkeypatch):
    import core.answering
    response = {"mode": "live", "status": "error", "answer": None,
                "sources": [], "message": "Software-only boundary fixture"}
    def fake_run(question, transcription_id):
        assert (question, transcription_id) == ("Where is the school?", 16)
        return response, None
    monkeypatch.setattr(core.answering, "run_answer", fake_run)
    assert answer_question("Where is the school?", 16) == response


def test_search_requires_a_completed_real_dataset(tmp_path, monkeypatch):
    monkeypatch.setenv("BERN_DATA_DIR", str(tmp_path / "not-built"))
    with pytest.raises(FileNotFoundError):
        search_records("Where is the school?")
