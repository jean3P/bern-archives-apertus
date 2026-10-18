"""Pure authored ownership controls; no Docker, GPU, server, or model execution."""

from pathlib import Path

import pytest

from scripts import serve_qwen
from core.config import ROOT


def info():
    return {"Id": "owned-fixture", "Config": {"Labels": {"bern.project": str(ROOT),
        "bern.owner": "jean3P/bern-archives-apertus", "bern.role": "qwen-evidence"},
        "Image": "pinned", "Cmd": ["vllm", "serve"],
        "Env": ["HF_HUB_OFFLINE=1", "TRANSFORMERS_OFFLINE=1"]},
        "HostConfig": {"PortBindings": {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8012"}]}},
        "Mounts": [{"Source": str(Path("synthetic-model").resolve()), "Destination": "/model", "RW": False}]}


def test_exact_owned_qwen_profile_is_required():
    serve_qwen.verify_owned(info(), "owned-fixture", Path("synthetic-model").resolve(), "pinned", 8012, ["vllm", "serve"])


@pytest.mark.parametrize("change", ["id", "role", "argv", "public", "writable", "online"])
def test_mismatched_service_cannot_be_stopped(change):
    value = info()
    if change == "id":
        value["Id"] = "someone-else"
    elif change == "role":
        value["Config"]["Labels"]["bern.role"] = "apertus"
    elif change == "argv":
        value["Config"]["Cmd"] = ["different"]
    elif change == "public":
        value["HostConfig"]["PortBindings"]["8000/tcp"][0]["HostIp"] = "0.0.0.0"
    elif change == "writable":
        value["Mounts"][0]["RW"] = True
    else:
        value["Config"]["Env"] = []
    with pytest.raises(ValueError, match="preserve"):
        serve_qwen.verify_owned(value, "owned-fixture", Path("synthetic-model").resolve(), "pinned", 8012, ["vllm", "serve"])


def test_unknown_or_busy_metrics_cannot_authorize_stop():
    assert serve_qwen.idle('vllm:num_requests_running{model="x"} 0\nvllm:num_requests_waiting{model="x"} 0')
    assert not serve_qwen.idle("")
    assert not serve_qwen.idle('vllm:num_requests_running{model="x"} 0')
    assert not serve_qwen.idle('vllm:num_requests_running{model="x"} 1\nvllm:num_requests_waiting{model="x"} 0')
