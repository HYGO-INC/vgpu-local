import argparse
import json
import os
from pathlib import Path
import subprocess

def main():
    parser = argparse.ArgumentParser(description="Local GPU tools; no cloud account required")
    commands = parser.add_subparsers(dest="action", required=True)
    # The starter install has no third-party dependencies. Optional command
    # registration must not import their implementations until requested.
    import sys
    selected = sys.argv[1:2]
    if selected == ["runtime"]:
        try:
            from .runtime_cli import register as register_runtime
        except ModuleNotFoundError:
            parser.exit(2, "Install the optional vgpu-local[runtime] extra for runtime commands.\n")
        register_runtime(commands)
    else:
        commands.add_parser("runtime", help="Optional background runtime and local console")
    if selected == ["interruption"]:
        try:
            from .interruption_cli import register
        except ModuleNotFoundError:
            parser.exit(2, "Install the optional vgpu-local[control] extra for interruption commands.\n")
        register(commands)
    else:
        commands.add_parser("interruption", help="Optional interruption control extra")
    if selected == ["kubernetes"]:
        try:
            from .kubernetes_cli import register as register_kubernetes
        except ModuleNotFoundError:
            parser.exit(2, "Install the optional vgpu-local[kubernetes] extra for cluster commands.\n")
        register_kubernetes(commands)
    else:
        commands.add_parser("kubernetes", help="Optional existing-cluster integration")
    from .starter import register as register_starter
    register_starter(commands)
    inventory = commands.add_parser("inventory", help="Report allocatable GPUs; this is not free capacity")
    inventory.add_argument("--nodes-json", type=Path, help="Read a saved kubectl nodes response offline")
    inventory.add_argument("--context", help="Explicit Kubernetes context for live inventory")
    profile = commands.add_parser("capabilities")
    profile.add_argument("provider", choices=["kubernetes", "simulator"])
    cloud = commands.add_parser("cloud", help="Explicit cloud connection; does not enable spending or contribution")
    cloud_commands = cloud.add_subparsers(dest="cloud_action", required=True)
    for name in ("connect", "status", "disconnect", "renew"):
        connection = cloud_commands.add_parser(name)
        connection.add_argument("--config", type=Path, default=Path.home() / ".config/vgpu-local/cloud.json")
        if name == "connect":
            connection.add_argument("--endpoint", default="https://vgpu.com")
            connection.add_argument("--tenant", help="Legacy manual enrollment only")
            connection.add_argument("--project", help="Legacy manual enrollment only")
            connection.add_argument("--name", required=True)
            connection.add_argument("--restart", action="store_true", help="Explicitly replace an unfinished device request; never an enrolled connection")
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
        if args.action in {"doctor", "engine"}:
            from .starter import run
            result = run(args)
        elif args.action == "runtime":
            from .runtime_cli import run
            result = run(args)
        elif args.action == "interruption":
            from .interruption_cli import run
            result = run(args)
        elif args.action == "kubernetes":
            from .kubernetes_cli import run
            result = run(args)
        elif args.action == "cloud":
            from .cloud import CloudConnection, SystemKeyring
            client = CloudConnection(args.config, SystemKeyring())
            if args.cloud_action == "connect":
                if args.tenant or args.project:
                    if not args.tenant or not args.project or args.restart:
                        raise ValueError("manual_enrollment_requires_tenant_and_project_without_restart")
                    result = client.connect(endpoint=args.endpoint, tenant_id=args.tenant, project_id=args.project,
                                            name=args.name, user_access_token=os.environ.get("VGPU_USER_ACCESS_TOKEN", ""))
                else:
                    from .device import DeviceConnection
                    def announce(url, code):
                        print(f"Open {url} and enter {code}. Match this code and choose your project.", file=sys.stderr, flush=True)
                    result = DeviceConnection(client).connect(endpoint=args.endpoint, name=args.name,
                                                              announce=announce, restart=args.restart)
            elif args.cloud_action == "status":
                result = client.status()
            elif args.cloud_action == "renew":
                result = client.renew()
            else:
                result = client.disconnect()
        elif args.action == "capabilities":
            from .capabilities import capabilities
            result = capabilities(args.provider).model_dump()
        elif args.action == "inventory":
            from .kubernetes import gpu_inventory
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
            from .kubernetes import render_job
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
    except KeyboardInterrupt:
        parser.exit(130, "Command interrupted. Rerun the same connection command to resume.\n")
    except ModuleNotFoundError:
        extra = args.action if args.action in {"cloud", "runtime"} else "control"
        parser.exit(2, f"Install the optional vgpu-local[{extra}] extra for this command.\n")
    except (ValueError, OSError, subprocess.SubprocessError, RuntimeError) as error:
        parser.exit(2, str(error) + "\n")
