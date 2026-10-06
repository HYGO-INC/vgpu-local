import argparse
import json
import os
from pathlib import Path
import subprocess

from .capabilities import capabilities
from .kubernetes import gpu_inventory, render_job


def main():
    parser = argparse.ArgumentParser(description="Local GPU tools; no cloud account required")
    commands = parser.add_subparsers(dest="action", required=True)
    from .interruption_cli import register
    register(commands)
    inventory = commands.add_parser("inventory", help="Report allocatable GPUs; this is not free capacity")
    inventory.add_argument("--nodes-json", type=Path, help="Read a saved kubectl nodes response offline")
    inventory.add_argument("--context", help="Explicit Kubernetes context for live inventory")
    profile = commands.add_parser("capabilities")
    profile.add_argument("provider", choices=["vast", "runpod", "theta", "kubernetes", "simulator"])
    cloud = commands.add_parser("cloud", help="Explicit cloud connection; does not enable spending or contribution")
    cloud_commands = cloud.add_subparsers(dest="cloud_action", required=True)
    for name in ("connect", "status", "disconnect", "renew"):
        connection = cloud_commands.add_parser(name)
        connection.add_argument("--config", type=Path, default=Path.home() / ".config/vgpu-local/cloud.json")
        if name == "connect":
            connection.add_argument("--endpoint", required=True)
            connection.add_argument("--tenant", required=True)
            connection.add_argument("--project", required=True)
            connection.add_argument("--name", required=True)
    for name in ("render-job", "submit-job"):
        job = commands.add_parser(name, help="Create a suspended job admitted by your installed Kueue")
        job.add_argument("--name", required=True)
        job.add_argument("--namespace", default="vgpu-local")
        job.add_argument("--queue", default="local-gpu")
        job.add_argument("--image", required=True)
        job.add_argument("--gpus", type=int, default=1)
        job.add_argument("--gpu-resource", default="nvidia.com/gpu")
        job.add_argument("--gpu-product")
        job.add_argument("--runtime-class", default="nvidia")
        if name == "submit-job":
            job.add_argument("--context", required=True)
        job.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        if args.action == "interruption":
            from .interruption_cli import run
            result = run(args)
        elif args.action == "cloud":
            from .cloud import CloudConnection, SystemKeyring
            client = CloudConnection(args.config, SystemKeyring())
            if args.cloud_action == "connect":
                result = client.connect(endpoint=args.endpoint, tenant_id=args.tenant, project_id=args.project,
                                        name=args.name, user_access_token=os.environ.get("VGPU_USER_ACCESS_TOKEN", ""))
            elif args.cloud_action == "status":
                result = client.status()
            elif args.cloud_action == "renew":
                result = client.renew()
            else:
                result = client.disconnect()
        elif args.action == "capabilities":
            result = capabilities(args.provider).model_dump()
        elif args.action == "inventory":
            if args.nodes_json:
                nodes = json.loads(args.nodes_json.read_text(encoding="utf-8"))
            elif args.context:
                output = subprocess.run(["kubectl", "--context", args.context, "get", "nodes", "-o", "json"],
                                        check=True, capture_output=True, text=True, timeout=30)
                nodes = json.loads(output.stdout)
            else:
                parser.error("provide --nodes-json or an explicit --context")
            result = gpu_inventory(nodes)
        else:
            argv = args.command[1:] if args.command[:1] == ["--"] else args.command
            result = render_job(name=args.name, namespace=args.namespace, queue=args.queue,
                                image=args.image, command=argv, gpu_count=args.gpus,
                                gpu_resource=args.gpu_resource, runtime_class=args.runtime_class,
                                gpu_product=args.gpu_product)
            if args.action == "submit-job":
                # Fail closed if Kueue/queue is absent. kubectl create never overwrites another job.
                subprocess.run(["kubectl", "--context", args.context, "-n", args.namespace,
                                "get", "localqueue", args.queue, "-o", "name"], check=True, timeout=30)
                subprocess.run(["kubectl", "--context", args.context, "create", "-f", "-"],
                                input=json.dumps(result), text=True, check=True, timeout=30)
                return
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, subprocess.SubprocessError, RuntimeError) as error:
        parser.exit(2, str(error) + "\n")
