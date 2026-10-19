"""First-run setup is useful without overwriting private inputs or stopping services."""

from argparse import Namespace
import os
import socket
from types import SimpleNamespace

from dotenv import dotenv_values
import pytest

from scripts import setup


def options(**changes):
    fields = dict.fromkeys(("client_id", "data_dir", "runs_dir", "original_reviews_dir",
                           "account_reviews_dir", "model_url", "model_id", "live_port", "review_port"))
    return Namespace(**(fields | changes))


def inputs(tmp_path, monkeypatch):
    data = tmp_path / "data with spaces #1"
    data.mkdir()
    for name in ("_SUCCESS.json", "search.sqlite3"):
        (data / name).write_text("synthetic marker, not a real dataset")
    runs = tmp_path / "saved runs"
    completed = runs / "synthetic-run"
    completed.mkdir(parents=True)
    for name in ("_COMPLETE.json", "run-manifest.json"):
        (completed / name).write_text("synthetic marker")
    monkeypatch.setattr(setup.getpass, "getpass", lambda label: "synthetic$KEY#with'quote")
    return options(data_dir=str(data), runs_dir=str(runs), client_id="synthetic-client",
                   original_reviews_dir=str(tmp_path / "originals"), account_reviews_dir=str(tmp_path / "accounts"),
                   live_port="17870", review_port="17873", model_url="http://127.0.0.1:8010/v1",
                   model_id="synthetic/model")


def test_fresh_setup_creates_private_files_and_keeps_input_bytes(tmp_path, monkeypatch, capsys):
    args = inputs(tmp_path, monkeypatch)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    compose, host = setup.prepare(tmp_path, args, native_linux=True)
    assert host and compose["BERN_SETUP_HOST_NETWORK"] == "1"
    assert compose["COMPOSE_FILE"] == "compose.yaml:compose.host-network.yaml"
    assert compose["COMPOSE_PROJECT_NAME"] == "bern-archives-ui"
    assert compose["BERN_CONTAINER_UID"] == (os.getuid() if hasattr(os, "getuid") else 1000)
    assert all(p.read_bytes() == value for p, value in before.items())
    config = dotenv_values(tmp_path / ".env.review-oauth")
    assert len(config["BERN_REVIEW_SESSION_SECRET"]) >= 32
    assert config["BERN_REVIEW_HF_REDIRECT_URI"] == "http://127.0.0.1:17873/auth/huggingface/callback"
    assert dotenv_values(tmp_path / ".env", interpolate=False)["BERN_APERTUS_API_KEY"] == "synthetic$KEY#with'quote"
    assert config["BERN_REVIEW_SESSION_SECRET"] not in capsys.readouterr().out
    if os.name != "nt":
        assert all((tmp_path / name).stat().st_mode & 0o777 == 0o600 for name in (".env", ".env.compose", ".env.review-oauth"))


def test_second_prepare_reuses_every_file_without_prompts_or_secret_rotation(tmp_path, monkeypatch):
    setup.prepare(tmp_path, inputs(tmp_path, monkeypatch), native_linux=True)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    monkeypatch.setattr(setup, "ask", lambda *args: pytest.fail("Unexpected prompt"))
    setup.prepare(tmp_path, options(), native_linux=True)
    assert all(p.read_bytes() == value for p, value in before.items())


@pytest.mark.parametrize("change", ["missing-data", "missing-run", "nested-accounts", "equal-ports", "bad-url"])
def test_invalid_inputs_create_no_private_files(tmp_path, monkeypatch, change):
    args = inputs(tmp_path, monkeypatch)
    if change == "missing-data":
        args.data_dir = str(tmp_path / "absent")
    elif change == "missing-run":
        args.runs_dir = str(tmp_path)
    elif change == "nested-accounts":
        args.account_reviews_dir = str(tmp_path / "saved runs/synthetic-run/accounts")
    elif change == "equal-ports":
        args.review_port = args.live_port
    else:
        args.model_url = "https://secret:password@example.org/v1"
    with pytest.raises((setup.SetupError, ValueError)):
        setup.prepare(tmp_path, args, native_linux=True)
    assert not list(tmp_path.glob(".env*"))


def test_callback_mismatch_keeps_all_private_bytes(tmp_path, monkeypatch):
    setup.prepare(tmp_path, inputs(tmp_path, monkeypatch), native_linux=True)
    path = tmp_path / ".env.review-oauth"
    path.write_text(path.read_text().replace(":17873/", ":17863/"))
    before = {p: p.read_bytes() for p in tmp_path.glob(".env*")}
    with pytest.raises(setup.SetupError, match="callback"):
        setup.prepare(tmp_path, options(), native_linux=True)
    assert all(p.read_bytes() == value for p, value in before.items())


def test_desktop_rewrites_only_default_loopback_model_host(tmp_path, monkeypatch):
    args = inputs(tmp_path, monkeypatch)
    args.model_url = None
    monkeypatch.setattr(setup, "ask", lambda label, default="": default)
    compose, host = setup.prepare(tmp_path, args, native_linux=False)
    assert not host
    assert compose["BERN_DOCKER_MODEL_URL"] == "http://host.docker.internal:8010/v1"


def test_launch_uses_quiet_config_wait_and_correct_override(tmp_path, monkeypatch):
    calls = []
    def docker(args, root, **kw):
        calls.append(args)
        return ""
    monkeypatch.setattr(setup, "docker", docker)
    compose = {"BERN_LIVE_PORT": "18760", "BERN_REVIEW_PORT": "18763"}
    setup.launch(tmp_path, compose, True, "synthetic-project")
    assert len(calls) == 3 and calls[1][-2:] == ["config", "--quiet"]
    assert "compose.host-network.yaml" in calls[2]
    assert calls[2][-6:] == ["up", "--build", "-d", "--wait", "--wait-timeout", "180"]
    assert not any("down" in call or "restart" in call for call in calls)


def test_occupied_port_does_not_start_or_stop_any_container(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(setup, "docker", lambda *args, **kw: calls.append(args))
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        with pytest.raises(setup.SetupError, match="already in use"):
            setup.launch(tmp_path, {"BERN_LIVE_PORT": server.getsockname()[1]}, False, "synthetic")
    assert calls == []


def test_docker_failure_does_not_print_secret_bearing_diagnostics(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(setup.subprocess, "run", lambda *args, **kw: SimpleNamespace(
        returncode=1, stdout="private=must-not-print", stderr="private=must-not-print"))
    with pytest.raises(setup.SetupError):
        setup.docker(["compose", "config", "--quiet"], tmp_path)
    assert "must-not-print" not in str(capsys.readouterr())


def test_dollar_paths_and_keys_roundtrip_literally(tmp_path):
    path = tmp_path / ".env.test"
    value = "C:/my folder/Jean's $HOME #literal"
    setup.write_settings(path, {"VALUE": value})
    assert dotenv_values(path, interpolate=False)["VALUE"] == value
    with pytest.raises(FileExistsError):
        setup.write_settings(path, {"VALUE": "replaced"})


def test_project_owned_by_another_checkout_is_not_recreated(tmp_path, monkeypatch):
    import json
    calls = []
    def docker(args, root, **kw):
        calls.append(args)
        if args[0] == "inspect":
            return json.dumps([{"Config": {"Labels": {"com.docker.compose.project.working_dir": "/different-checkout"}}}])
        return "synthetic-container"
    monkeypatch.setattr(setup, "docker", docker)
    with pytest.raises(setup.SetupError, match="another checkout"):
        setup.launch(tmp_path, {"BERN_LIVE_PORT": "18760", "BERN_REVIEW_PORT": "18763"}, False, "synthetic")
    assert not any("up" in call or "down" in call or "restart" in call for call in calls)
