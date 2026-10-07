"""Durable local Kubernetes commands. No cloud identity or service is required."""
import json
from pathlib import Path
import sqlite3

from .contracts.models import BackendRequest
from .errors import KeyConflict, OutcomeUnknown, UnsupportedCapability
from .journal import Journal, scope
from .kubernetes_api import KubernetesAPI
from .kubernetes_backend import GpuClass, KubernetesBackend
from .kubernetes_config import validate_config


def register(commands):
    parser = commands.add_parser("kubernetes", help="Durable jobs in an explicitly configured local cluster")
    actions = parser.add_subparsers(dest="kubernetes_action", required=True)
    initialize = actions.add_parser("init", help="Create a new durable local journal; makes no cluster calls")
    initialize.add_argument("--journal", type=Path, required=True)
    validate = actions.add_parser("validate", help="Validate operator configuration offline")
    validate.add_argument("--config", type=Path, required=True)
    for name in ("provision", "observe", "release"):
        command = actions.add_parser(name)
        command.add_argument("--config", type=Path, required=True)
        command.add_argument("--journal", type=Path, required=True)
        command.add_argument("--account-id", required=True)
        command.add_argument("--request", type=Path, required=True)


def read_object(path):
    with path.open("rb") as source: raw = source.read(65_537)
    if len(raw) > 65_536: raise ValueError("Input exceeds 64 KiB")
    def unique(pairs):
        result = {}
        for key,value in pairs:
            if key in result: raise ValueError("Duplicate JSON key")
            result[key] = value
        return result
    def invalid(_): raise ValueError("Non-finite JSON value")
    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)
    except RecursionError:
        raise ValueError("JSON nesting exceeds limit") from None
    if not isinstance(value, dict): raise ValueError("JSON object required")
    pending = [(value,0)]
    while pending:
        item,depth = pending.pop()
        if depth > 32: raise ValueError("JSON nesting exceeds limit")
        if isinstance(item,dict): pending.extend((child,depth+1) for child in item.values())
        elif isinstance(item,list): pending.extend((child,depth+1) for child in item)
    return value


def run(args):
    if args.kubernetes_action == "init":
        # Exclusive creation prevents silently replacing recovery evidence.
        # Keep a failed initialization file for diagnosis; never delete an
        # operator journal as error recovery.
        with args.journal.open("xb"): pass
        Journal(args.journal)
        return {"status":"initialized"}
    config = validate_config(read_object(args.config))
    if args.kubernetes_action == "validate":
        return {"status":"valid", "context":config["context"], "namespace":config["namespace"],
                "gpu_classes":list(config["gpu_classes"])}
    request = BackendRequest.model_validate(read_object(args.request))
    if request.provider != "kubernetes" or request.account_id != args.account_id:
        raise ValueError("Request must match the operator's Kubernetes account binding")
    if not args.journal.is_file():
        raise ValueError("Journal missing; restore existing recovery evidence or initialize a new site journal explicitly")
    try: journal = Journal(args.journal, create=False)
    except sqlite3.Error: raise ValueError("Existing journal is unavailable or invalid; no cluster call performed") from None
    if args.kubernetes_action != "provision":
        try: journal.read(scope(request))
        except KeyError: raise ValueError("No operation receipt; no cluster call performed") from None
    api = None
    try:
        api = KubernetesAPI(context=config["context"], namespace=config["namespace"],
                            kubeconfig=config.get("kubeconfig"), queue_api_version=config["queue_api_version"])
        backend = KubernetesBackend(journal, api, account_id=args.account_id,
            namespace=config["namespace"],namespace_uid=config["namespace_uid"],queue=config["queue"],
            region=config["region"],runtime_class=config["runtime_class"],
            gpu_classes={name:GpuClass(**gpu) for name,gpu in config["gpu_classes"].items()})
        return getattr(backend,args.kubernetes_action)(request).model_dump(mode="json")
    except (OutcomeUnknown, KeyConflict, UnsupportedCapability) as error:
        raise RuntimeError(type(error).__name__+": preserve this journal and request; no automatic resubmission") from None
    except Exception:
        raise RuntimeError("OutcomeUnknown: client or cluster response unavailable; preserve this journal and request") from None
    finally:
        if api is not None:
            try: api.close()
            except Exception: pass
