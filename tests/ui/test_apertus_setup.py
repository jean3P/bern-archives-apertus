"""Pinned download/setup controls; no network, weight downloads or GPU execution."""

import json
from pathlib import Path
from types import SimpleNamespace

from dotenv import dotenv_values
import pytest

from scripts import setup_apertus as setup


def snapshot(tmp_path):
    path = tmp_path / setup.REVISION
    path.mkdir()
    for name in ("config.json", "tokenizer.json", "tokenizer_config.json"):
        (path / name).write_text("{}")
    (path / "model.safetensors.index.json").write_text(json.dumps({"weight_map": {"synthetic.weight": "one.safetensors"}}))
    (path / "one.safetensors").write_bytes(b"SYNTHETIC TEST BYTES, NOT WEIGHTS")
    return path


def test_offline_reuses_pinned_cache_and_never_calls_online_download(tmp_path, monkeypatch):
    cached = snapshot(tmp_path)
    calls = []
    def download(**kwargs):
        calls.append(kwargs)
        assert kwargs["local_files_only"] is True
        return str(cached)
    monkeypatch.setattr(setup, "snapshot_download", download)
    assert setup.acquire(tmp_path / "cache", offline=True) == cached
    assert len(calls) == 1 and calls[0]["revision"] == setup.REVISION


def test_dry_run_never_downloads_weights_or_writes_server_config(tmp_path, monkeypatch):
    calls = []
    def download(**kwargs):
        calls.append(kwargs)
        assert kwargs["dry_run"]
        return [SimpleNamespace(commit_hash=setup.REVISION, file_size=100, will_download=True)]
    monkeypatch.setattr(setup, "snapshot_download", download)
    assert setup.acquire(tmp_path / "cache", dry_run=True) is None
    assert len(calls) == 1 and not list(tmp_path.iterdir())


def test_download_binds_revision_and_keeps_resume_defaults(tmp_path, monkeypatch):
    cached = snapshot(tmp_path)
    calls = []
    def download(**kwargs):
        calls.append(kwargs)
        if kwargs.get("dry_run"):
            return [SimpleNamespace(commit_hash=setup.REVISION, file_size=100, will_download=True)]
        return str(cached)
    monkeypatch.setattr(setup, "snapshot_download", download)
    monkeypatch.setattr(setup.shutil, "disk_usage", lambda path: SimpleNamespace(free=10 * 1024**3))
    assert setup.acquire(tmp_path / "cache", yes=True) == cached
    assert len(calls) == 2
    assert all(call["revision"] == setup.REVISION and call["repo_id"] == setup.MODEL_ID for call in calls)
    assert "force_download" not in calls[1] and "token" not in calls[1]


@pytest.mark.parametrize("change", ["low-disk", "different-pin", "unknown-size", "cancel"])
def test_invalid_plan_or_no_approval_never_starts_download(tmp_path, monkeypatch, change):
    calls = []
    def download(**kwargs):
        calls.append(kwargs)
        assert kwargs.get("dry_run")
        return [SimpleNamespace(commit_hash="wrong" if change == "different-pin" else setup.REVISION,
                                file_size=None if change == "unknown-size" else 100, will_download=True)]
    monkeypatch.setattr(setup, "snapshot_download", download)
    monkeypatch.setattr(setup.shutil, "disk_usage", lambda path: SimpleNamespace(free=0 if change == "low-disk" else 10 * 1024**3))
    monkeypatch.setattr("builtins.input", lambda prompt: "no")
    with pytest.raises(setup.SetupError):
        setup.acquire(tmp_path / "cache")
    assert len(calls) == 1


@pytest.mark.parametrize("change", ["missing-tokenizer", "missing-shard", "traversal", "bad-mapping"])
def test_incomplete_or_unsafe_checkpoint_is_rejected(tmp_path, change):
    cached = snapshot(tmp_path)
    if change == "missing-tokenizer":
        (cached / "tokenizer.json").unlink()
    elif change == "missing-shard":
        (cached / "one.safetensors").unlink()
    else:
        (cached / "model.safetensors.index.json").write_text(json.dumps({"weight_map": {
            "weight": "../one.safetensors" if change == "traversal" else []}}))
    with pytest.raises(setup.SetupError):
        setup.verify_snapshot(cached)


def test_server_settings_are_private_idempotent_and_separate_from_web_settings(tmp_path):
    cached = snapshot(tmp_path)
    (tmp_path / ".env").write_text("keep web settings")
    path = setup.configure_server(tmp_path, cached)
    before = path.read_bytes()
    setup.configure_server(tmp_path, cached)
    assert path.read_bytes() == before and (tmp_path / ".env").read_text() == "keep web settings"
    config = dotenv_values(path)
    assert config["BERN_APERTUS_SNAPSHOT"] == cached.as_posix()
    assert config["COMPOSE_PROJECT_NAME"] == "bern-apertus-local"
    with pytest.raises(setup.SetupError, match="kept unchanged"):
        setup.configure_server(tmp_path, cached, server_port=8020)
    assert path.read_bytes() == before


def test_compose_pins_gpu_image_and_keeps_model_read_only_on_loopback():
    text = (setup.ROOT / "compose.apertus.yaml").read_text()
    assert setup.IMAGE in text
    assert "127.0.0.1:" in text and "read_only: true" in text
    assert 'HF_HUB_OFFLINE: "1"' in text and "device_ids:" in text
    assert "HF_TOKEN" not in text and "latest" not in text and "restart:" not in text
