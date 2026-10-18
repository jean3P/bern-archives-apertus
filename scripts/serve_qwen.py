"""Explicit Bern-only Qwen service; never starts/stops Apertus or another job."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import time
from urllib.parse import urlparse

import httpx

from core.config import ROOT, qwen_settings
from core.question_evidence import QWEN_MODEL
from scripts.serve_apertus import inspect, run

STATE = ROOT / "runs/qwen-owner.json"
CONFIG_SHA256 = "d2dd0c60d01b9e195d9447c52da61c7302d28828524914c044d9c6e1b81d0427"
INDEX_SHA256 = "06c952c569285870b811989b794b9766493e280fb77fbcb957fc4e5fcf25403a"


def profile():
    config = qwen_settings()
    endpoint = urlparse(config.base_url)
    if endpoint.hostname != "127.0.0.1" or endpoint.port is None or config.model != QWEN_MODEL:
        raise ValueError("Owned Qwen serving requires the exact model and an explicit loopback port")
    model_dir = Path(os.environ["BERN_QWEN_MODEL_DIR"]).resolve(strict=True)
    for name, expected in (("config.json", CONFIG_SHA256), ("model.safetensors.index.json", INDEX_SHA256)):
        if hashlib.sha256((model_dir / name).read_bytes()).hexdigest() != expected:
            raise ValueError("Qwen cached metadata differs from the selected checkpoint")
    index = json.loads((model_dir / "model.safetensors.index.json").read_text())
    shards = sorted(set(index["weight_map"].values()))
    if len(shards) != 14 or any(Path(name).name != name or not (model_dir / name).is_file() for name in shards):
        raise ValueError("The complete indexed local Qwen checkpoint is required; downloads are disabled")
    image = os.environ["BERN_VLLM_IMAGE"]
    if not re.fullmatch(r"[^\s]+@sha256:[a-f0-9]{64}", image):
        raise ValueError("Use the already cached digest-pinned vLLM image")
    name = os.environ.get("BERN_QWEN_CONTAINER_NAME", "bern-qwen-20261018")
    if not re.fullmatch(r"bern-qwen-[A-Za-z0-9_-]+", name):
        raise ValueError("A separate Bern Qwen container name is required")
    fraction = float(os.environ.get("BERN_QWEN_GPU_MEMORY_UTILIZATION", ".72"))
    if not .68 <= fraction <= .85:
        raise ValueError("Qwen BF16 needs an explicitly bounded memory fraction between .68 and .85")
    argv = ["vllm", "serve", "/model", "--served-model-name", config.model,
        "--dtype", "bfloat16", "--gpu-memory-utilization", str(fraction),
        "--cpu-offload-gb", "0", "--max-model-len", "8192", "--max-num-seqs", "1",
        "--generation-config", "vllm", "--limit-mm-per-prompt", '{"image":0,"video":0,"audio":0}',
        "--enforce-eager", "--chat-template-content-format", "string"]
    command = ["docker", "run", "--rm", "-d", "--pull=never", "--name", name,
        "--runtime=nvidia", "--ipc=host", "--label", "bern.project=" + str(ROOT),
        "--label", "bern.owner=jean3P/bern-archives-apertus", "--label", "bern.role=qwen-evidence",
        "-p", f"127.0.0.1:{endpoint.port}:8000", "-e", "NVIDIA_VISIBLE_DEVICES=all",
        "-e", "NVIDIA_DRIVER_CAPABILITIES=compute,utility", "-e", "HF_HUB_OFFLINE=1",
        "-e", "TRANSFORMERS_OFFLINE=1", "-e", "HF_HUB_DISABLE_TELEMETRY=1",
        "-e", "VLLM_USE_V2_MODEL_RUNNER=0", "-v", str(model_dir) + ":/model:ro", image] + argv
    return config, model_dir, image, name, fraction, endpoint.port, argv, command


def verify_owned(info, recorded_id, model_dir, image, port, argv):
    labels = info["Config"].get("Labels", {})
    env = info["Config"].get("Env", [])
    checks = [info["Id"] == recorded_id, labels.get("bern.project") == str(ROOT),
        labels.get("bern.owner") == "jean3P/bern-archives-apertus", labels.get("bern.role") == "qwen-evidence",
        info["Config"]["Image"] == image, info["Config"]["Cmd"] == argv,
        info["HostConfig"]["PortBindings"] == {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(port)}]},
        all(value in env for value in ("HF_HUB_OFFLINE=1", "TRANSFORMERS_OFFLINE=1")),
        any(m["Source"] == str(model_dir) and m["Destination"] == "/model" and not m["RW"] for m in info["Mounts"])]
    if not all(checks):
        raise ValueError("Qwen ownership/profile mismatch; preserve the service")


def idle(metrics):
    for prefix in ("vllm:num_requests_running{", "vllm:num_requests_waiting{"):
        values = [float(line.rsplit(" ", 1)[1]) for line in metrics.splitlines() if line.startswith(prefix)]
        if not values or any(value != 0 for value in values):
            return False
    return True


def save(record):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Explicit owned Qwen serving, with no generation requests")
    parser.add_argument("action", choices=("start", "status", "stop"))
    args = parser.parse_args()
    config, model_dir, image, name, fraction, port, argv, command = profile()
    info = inspect(name)
    if args.action == "start" and info is None:
        gpu = run(["nvidia-smi", "--query-gpu=memory.total,memory.free", "--format=csv,noheader,nounits"])
        if "\n" in gpu:
            raise ValueError("Select a GPU explicitly; this helper will not choose among other jobs")
        total, free = map(int, gpu.split(","))
        if free < total * fraction + 2048:
            raise ValueError("Insufficient free GPU memory; no Apertus or unrelated job will be stopped")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
        run(["docker", "image", "inspect", image])
        owned = run(command)
        record = {"container_id": owned, "command": command, "ready": False,
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "metadata_sha256": {"config.json": CONFIG_SHA256, "model.safetensors.index.json": INDEX_SHA256},
            "full_weight_bytes_rehashed": False}
        save(record)
    else:
        if not STATE.exists():
            raise ValueError("No matching Qwen owner receipt; preserve any existing service")
        record = json.loads(STATE.read_text())
        info = inspect(record["container_id"])
        if info is None:
            print("Recorded Bern Qwen service is not running")
            return
        verify_owned(info, record["container_id"], model_dir, image, port, argv)
        if args.action == "status":
            print(json.dumps({"id": info["Id"], "running": info["State"]["Running"], "base_url": config.base_url}))
            return
        if args.action == "stop":
            with httpx.Client(timeout=5, trust_env=False) as client:
                response = client.get(config.base_url.removesuffix("/v1") + "/metrics")
                response.raise_for_status()
            if not idle(response.text):
                raise ValueError("Qwen is busy or idle status is unknown; leave it running")
            print(run(["docker", "stop", "-t", "30", info["Id"]]))
            record["stopped_at_utc"] = datetime.now(timezone.utc).isoformat()
            save(record)
            return
    tick = time.perf_counter()
    owned = record["container_id"]
    try:
        while time.perf_counter() - tick < 600:
            info = inspect(owned)
            if not info or not info["State"]["Running"]:
                raise RuntimeError("Owned Qwen exited; inspect retained logs, do not restart other jobs")
            verify_owned(info, owned, model_dir, image, port, argv)
            try:
                with httpx.Client(timeout=3, trust_env=False) as client:
                    response = client.get(config.base_url + "/models")
                    response.raise_for_status()
                models = response.json()["data"]
                if len(models) == 1 and models[0]["id"] == config.model and models[0].get("max_model_len") == 8192:
                    record.update(ready=True, models=models, startup_seconds=time.perf_counter() - tick)
                    save(record)
                    print(json.dumps(record, indent=2))
                    return
            except (httpx.HTTPError, ValueError, KeyError):
                pass
            if int(time.perf_counter() - tick) % 20 < 2:
                print(f"Bern Qwen starting: {time.perf_counter() - tick:.0f}s", flush=True)
            time.sleep(2)
        raise TimeoutError("Qwen startup exceeded ten minutes")
    finally:
        logs = subprocess.run(["docker", "logs", owned], capture_output=True, text=True)
        (ROOT / "runs/qwen-server.log").write_text(logs.stdout + logs.stderr, encoding="utf-8")


if __name__ == "__main__":
    main()
