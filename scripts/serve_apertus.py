"""Own one Bern-only loopback vLLM container. Never stop another service."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from urllib.parse import urlparse

import httpx

from core.config import ROOT, settings

STATE = ROOT / "runs/apertus-owner.json"


def run(args):
    return subprocess.check_output(args, text=True).strip()


def inspect(container):
    result = subprocess.run(["docker", "inspect", container], text=True, capture_output=True)
    return json.loads(result.stdout)[0] if result.returncode == 0 else None


def profile():
    config = settings()
    cache = Path(os.environ["BERN_HF_CACHE"]).resolve(strict=True)
    revision = os.environ["BERN_MODEL_REVISION"]
    image = os.environ["BERN_VLLM_IMAGE"]
    name = os.environ.get("BERN_CONTAINER_NAME", "bern-apertus-20261018")
    fraction = float(os.environ.get("BERN_GPU_MEMORY_UTILIZATION", ".40"))
    if not name.startswith("bern-apertus-") or not .1 <= fraction <= .4:
        raise ValueError("Use a Bern-owned name and a reservation no greater than 40%")
    if "@sha256:" not in image or len(revision) != 40:
        raise ValueError("Pin the image digest and model revision")
    model_cache = cache / "models--swiss-ai--Apertus-v1.5-8B"
    if (model_cache / "refs/main").read_text().strip() != revision:
        raise ValueError("Cached revision differs from the configured pin")
    if not (model_cache / "snapshots" / revision / "config.json").is_file():
        raise ValueError("Pinned cached model is missing")
    port = urlparse(config.base_url).port or 80
    argv = ["vllm", "serve", config.model, "--served-model-name", config.model,
            "--revision", revision, "--dtype", "bfloat16", "--gpu-memory-utilization", str(fraction),
            "--cpu-offload-gb", "0", "--max-model-len", "8192", "--max-num-seqs", "1",
            "--generation-config", "vllm", "--limit-mm-per-prompt",
            '{"image":{"count":1,"width":1024,"height":1024},"video":0,"audio":0}',
            "--enforce-eager", "--chat-template-content-format", "string"]
    command = ["docker", "run", "--rm", "-d", "--pull=never", "--name", name,
               "--runtime=nvidia", "--ipc=host", "--label", "bern.project=" + str(ROOT),
               "--label", "bern.owner=jean3P/bern-archives-apertus",
               "-p", f"127.0.0.1:{port}:8000", "-e", "NVIDIA_VISIBLE_DEVICES=all",
               "-e", "NVIDIA_DRIVER_CAPABILITIES=compute,utility",
               "-e", "HF_HUB_OFFLINE=1", "-e", "TRANSFORMERS_OFFLINE=1",
               "-e", "HF_HUB_DISABLE_TELEMETRY=1", "-e", "VLLM_USE_V2_MODEL_RUNNER=0",
               "-v", str(cache) + ":/root/.cache/huggingface/hub:ro", image] + argv
    return config, cache, image, name, fraction, port, argv, command


def verify_owned(info, cache, image, port, argv):
    labels = info["Config"].get("Labels", {})
    checks = [labels.get("bern.project") == str(ROOT),
              labels.get("bern.owner") == "jean3P/bern-archives-apertus",
              info["Config"]["Image"] == image, info["Config"]["Cmd"] == argv,
              info["HostConfig"]["PortBindings"] == {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(port)}]},
              any(m["Source"] == str(cache) and m["Destination"] == "/root/.cache/huggingface/hub" and not m["RW"]
                  for m in info["Mounts"])]
    if not all(checks):
        raise ValueError("Ownership/configuration mismatch; preserve the existing container")


def save(value):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "status", "stop"))
    args = parser.parse_args()
    config, cache, image, name, fraction, port, argv, command = profile()
    if args.action == "start":
        info = inspect(name)
        if info is None:
            gpu = run(["nvidia-smi", "--query-gpu=memory.total,memory.free", "--format=csv,noheader,nounits"])
            if "\n" in gpu:
                raise ValueError("This setup expects one H100; do not select another job's GPU implicitly")
            total, free = map(int, gpu.split(","))
            if free < total * fraction + 4096:
                raise ValueError("Insufficient free memory; no other job will be stopped")
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", port))
            run(["docker", "image", "inspect", image])
            tick = time.perf_counter()
            owned = run(command)
            record = {"container_id": owned, "command": command,
                      "started_at_utc": datetime.now(timezone.utc).isoformat(), "ready": False}
            save(record)
        else:
            verify_owned(info, cache, image, port, argv)
            if not STATE.exists() or json.loads(STATE.read_text())["container_id"] != info["Id"]:
                raise ValueError("Existing container has no matching local receipt; preserve it")
            owned, record, tick = info["Id"], json.loads(STATE.read_text()), time.perf_counter()
        try:
            while time.perf_counter() - tick < 600:
                info = inspect(owned)
                if not info or not info["State"]["Running"]:
                    raise RuntimeError("Owned model server exited; inspect its retained logs")
                verify_owned(info, cache, image, port, argv)
                try:
                    with httpx.Client(timeout=3, trust_env=False) as client:
                        response = client.get(config.base_url + "/models")
                        response.raise_for_status()
                        models = response.json()["data"]
                    if len(models) == 1 and models[0]["id"] == config.model and models[0]["max_model_len"] == 8192:
                        record.update(ready=True, models=models, startup_seconds=time.perf_counter() - tick)
                        save(record)
                        print(json.dumps(record, indent=2))
                        return
                except (httpx.HTTPError, ValueError, KeyError):
                    pass
                if int(time.perf_counter() - tick) % 20 < 2:
                    print(f"Bern Apertus starting: {time.perf_counter() - tick:.0f}s", flush=True)
                time.sleep(2)
            raise TimeoutError("Model startup exceeded ten minutes")
        finally:
            logs = subprocess.run(["docker", "logs", owned], capture_output=True, text=True)
            (ROOT / "runs/apertus-server.log").write_text(logs.stdout + logs.stderr, encoding="utf-8")
    else:
        if not STATE.exists():
            raise ValueError("No owned-service receipt; no container will be stopped")
        record = json.loads(STATE.read_text())
        info = inspect(record["container_id"])
        if info is None:
            print("Recorded Bern service is not running")
            return
        verify_owned(info, cache, image, port, argv)
        if args.action == "status":
            print(json.dumps({"id": info["Id"], "running": info["State"]["Running"], "base_url": config.base_url}))
            return
        with httpx.Client(timeout=5, trust_env=False) as client:
            response = client.get(config.base_url.removesuffix("/v1") + "/metrics")
            response.raise_for_status()
        for prefix in ("vllm:num_requests_running{", "vllm:num_requests_waiting{"):
            values = [float(line.rsplit(" ", 1)[1]) for line in response.text.splitlines() if line.startswith(prefix)]
            if not values or any(value != 0 for value in values):
                raise ValueError("Bern service is busy or idle status is unknown; leave it running")
        print(run(["docker", "stop", "-t", "30", info["Id"]]))
        record["stopped_at_utc"] = datetime.now(timezone.utc).isoformat()
        save(record)


if __name__ == "__main__":
    main()
