"""Isolated upstream-engine qualification; this does not change host Python/CUDA."""
import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["pull", "preflight", "download", "benchmark"])
    parser.add_argument("--data-directory", required=True, type=Path)
    parser.add_argument("--profile", choices=["smoke", "480p"], default="smoke")
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=int, help="wall-time bound (default: 1800 for GPU runs, 7200 for downloads)")
    args = parser.parse_args()
    if not 1 <= args.runs <= 5: parser.error("--runs must be between 1 and 5")
    if args.timeout_seconds is not None and not 30 <= args.timeout_seconds <= 14_400:
        parser.error("--timeout-seconds must be between 30 and 14400")
    recipe = Path(__file__).resolve().parent
    lock = json.loads((recipe / "lock.json").read_text())
    data = args.data_directory.resolve()
    data.mkdir(parents=True, exist_ok=True)
    if args.action == "pull":
        subprocess.run(["docker", "pull", lock["image"]], check=True)
        return
    name = "vgpu-fastvideo-" + uuid4().hex[:12]
    gpu = args.action in {"preflight", "benchmark"}
    memory = str(lock['container_memory_gib'])+'g' if gpu else '4g'
    command = ["docker", "run", "--rm", "--name", name, "--cpus", "6", "--memory", memory,
               "--memory-swap", memory, "--shm-size", "1g", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges", "--network", "bridge" if args.action == "download" else "none",
               "--mount", f"type=bind,source={recipe},target=/recipe,readonly",
               "--mount", f"type=bind,source={data},target=/data",
               "--env", "HF_HOME=/data/huggingface", "--env", "HF_HUB_DISABLE_IMPLICIT_TOKEN=1",
               "--env", "HF_HUB_DISABLE_TELEMETRY=1", "--env", "HF_XET_CHUNK_CACHE_SIZE_BYTES=0",
               "--env", "HF_XET_RECONSTRUCT_WRITE_SEQUENTIALLY=1", "--env", "WANDB_MODE=disabled",
               "--env", "TOKENIZERS_PARALLELISM=false", "--env", "PYTHONUNBUFFERED=1"]
    command += ["--env", "RAY_USAGE_STATS_ENABLED=0", "--env", "FASTVIDEO_HOST_IP=127.0.0.1"]
    if gpu: command += ["--gpus", "device=0"]
    if args.action != "download": command += ["--env", "HF_HUB_OFFLINE=1", "--env", "TRANSFORMERS_OFFLINE=1"]
    command += ["--entrypoint", "/opt/venv/bin/python", lock["image"], "/recipe/inside.py", args.action,
                "--profile", args.profile, "--runs", str(args.runs)]
    print(f"Container: {name}; artifacts: {data}", flush=True)
    invocations = data / 'invocations'
    invocations.mkdir(exist_ok=True)
    record = dict(container=name, action=args.action, profile=args.profile, runs=args.runs,
                  started_at=datetime.now(timezone.utc).isoformat(), lock=lock, status='running')
    path = invocations / (name+'.json')
    path.write_text(json.dumps(record,indent=2),encoding='utf-8')
    try:
        result = subprocess.run(command,timeout=args.timeout_seconds or (1800 if gpu else 7200))
        record.update(exit_code=result.returncode,status='passed' if result.returncode == 0 else 'failed')
        result.check_returncode()
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
        # Stop this invocation only; never prune shared Docker resources.
        subprocess.run(['docker','stop','--timeout','10',name],timeout=30,check=False)
        record.update(status='aborted',reason=type(error).__name__)
        raise
    finally:
        record['finished_at'] = datetime.now(timezone.utc).isoformat()
        path.write_text(json.dumps(record,indent=2),encoding='utf-8')


if __name__ == "__main__":
    main()
