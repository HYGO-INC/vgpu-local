"""Local interruption commands. Operator state and workload mailboxes stay separate."""
from contextlib import ExitStack
import json
import math
from pathlib import Path
import time

from filelock import FileLock, Timeout

from .contracts.models import InterruptionRequest, InterruptionScope, InterruptionSourceNotice
from .interruption_files import InterruptionFiles
from .interruptions import InterruptionController
from .journal import Journal, fingerprint


def register(commands):
    root = commands.add_parser('interruption', help='Linux file notice/response exchange; no automatic reclamation')
    actions = root.add_subparsers(dest='interruption_action', required=True)
    publish = actions.add_parser('publish', help='Operator: persist a normalized source notice')
    publish.add_argument('--config', type=Path, required=True)
    publish.add_argument('--notice', type=Path, required=True)
    relay = actions.add_parser('relay', help='Operator: publish snapshots and commit participant responses')
    relay.add_argument('--config', type=Path, required=True)
    relay.add_argument('--initialize', action='store_true', help='Create restrictive mailbox directories; does not change ownership')
    relay.add_argument('--once', action='store_true')
    relay.add_argument('--interval-seconds', type=float, default=1)
    status = actions.add_parser('snapshot', help='Workload: read the scoped mailbox snapshot')
    status.add_argument('--mailbox', type=Path, required=True)
    status.add_argument('--scope', type=Path, required=True)
    status.add_argument('--participant', required=True)
    for name in ['submit', 'receipt']:
        parser = actions.add_parser(name, help='Workload: '+('submit one immutable response' if name == 'submit' else 'read a correlated receipt'))
        parser.add_argument('--mailbox', type=Path, required=True)
        parser.add_argument('--request', type=Path, required=True)
        parser.add_argument('--wait-seconds', type=float, default=0)


def document(path: Path, maximum=65536):
    with path.open('rb') as file:
        content = file.read(maximum+1)
    if len(content) > maximum:
        raise ValueError('Configuration or request exceeds the size limit')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError('Duplicate JSON property')
            result[key] = value
        return result
    def non_json(value): raise ValueError('Invalid JSON numeric constant')
    try:
        result = json.loads(content, object_pairs_hook=unique, parse_constant=non_json)
        if not isinstance(result, dict): raise ValueError('JSON input must be an object')
        return result
    except RecursionError as error:
        raise ValueError('Excessively nested JSON') from error


def configuration(path: Path):
    value = document(path)
    if not isinstance(value, dict) or set(value) != {'version', 'scope', 'journal', 'participants'} or type(value['version']) is not int or value['version'] != 1:
        raise ValueError('Invalid interruption relay configuration')
    scope = InterruptionScope.model_validate(value['scope'])
    participants = value['participants']
    if not isinstance(participants, list) or not 1 <= len(participants) <= 64:
        raise ValueError('Provide 1-64 registered participants')
    def location(item):
        if not isinstance(item, str) or not item or '\0' in item: raise ValueError('Invalid configured path')
        candidate = Path(item)
        return candidate if candidate.is_absolute() else path.resolve().parent/candidate
    paths = {}
    for participant in participants:
        if not isinstance(participant, dict) or set(participant) != {'id', 'mailbox'}:
            raise ValueError('Invalid participant registration')
        identity = participant['id']
        if not isinstance(identity, str) or not 1 <= len(identity) <= 255 or identity in paths:
            raise ValueError('Invalid or duplicate participant identity')
        paths[identity] = location(participant['mailbox'])
    # Resolving only for overlap detection must not remove symlinks from the
    # actual path passed to the descriptor transport, which rejects them.
    resolved = [mailbox.resolve() for mailbox in paths.values()]
    for index, mailbox in enumerate(resolved):
        if any(mailbox == other or mailbox in other.parents or other in mailbox.parents for other in resolved[index+1:]):
            raise ValueError('Participant mailboxes must be separate, non-nested directories')
    journal = location(value['journal']).resolve()
    if any(target == mailbox or mailbox in target.parents for target in [journal,path.resolve()] for mailbox in resolved):
        raise ValueError('Operator journal and configuration must be outside workload mailboxes')
    return scope, journal, paths


def relay(config: Path, *, once=False, initialize=False, interval=1):
    if not math.isfinite(interval) or not 0.05 <= interval <= 30:
        raise ValueError('Relay interval must be 0.05..30 seconds')
    scope, journal, paths = configuration(config)
    # This lock fences file publishers on one host. It is not a GPU or volume
    # fence and must not be used to qualify shared/network SQLite deployment.
    try:
        with FileLock(str(journal)+'.relay.lock', timeout=0):
            controller = InterruptionController(Journal(journal), scope, list(paths))
            with ExitStack() as stack:
                transports = {identity:stack.enter_context(InterruptionFiles(mailbox, scope, identity, create=initialize))
                              for identity,mailbox in paths.items()}
                while True:
                    counts = {identity:files.forward(controller) for identity,files in transports.items()}
                    snapshot = controller.snapshot()
                    for files in transports.values():
                        try: prior = files.snapshot()
                        except FileNotFoundError: continue
                        if (snapshot.cursor < prior.cursor or (snapshot.cursor == prior.cursor and
                                fingerprint(snapshot.model_dump(mode='json')) != fingerprint(prior.model_dump(mode='json')))):
                            raise RuntimeError('Journal is behind the published mailbox; restore its durable state')
                    for files in transports.values(): files.publish(snapshot)
                    result = {'cursor':snapshot.cursor, 'participants':counts}
                    if once: return result
                    print(json.dumps(result), flush=True)
                    time.sleep(interval)
    except Timeout as error:
        raise RuntimeError('Another relay owns this runtime journal') from error


def run(args):
    action = args.interruption_action
    if action == 'relay':
        return relay(args.config, once=args.once, initialize=args.initialize, interval=args.interval_seconds)
    if action == 'publish':
        scope, journal, paths = configuration(args.config)
        source = InterruptionSourceNotice.model_validate(document(args.notice))
        return InterruptionController(Journal(journal), scope, list(paths)).publish(source).model_dump(mode='json')
    if action == 'snapshot':
        scope = InterruptionScope.model_validate(document(args.scope))
        with InterruptionFiles(args.mailbox, scope, args.participant) as files:
            return files.snapshot().model_dump(mode='json')
    if not math.isfinite(args.wait_seconds) or not 0 <= args.wait_seconds <= 300:
        raise ValueError('Receipt wait must be 0..300 seconds')
    request = InterruptionRequest.model_validate(document(args.request))
    scope = InterruptionScope.model_validate({key:getattr(request,key) for key in InterruptionScope.model_fields})
    with InterruptionFiles(args.mailbox, scope, request.participant_id) as files:
        if action == 'submit': files.submit(request)
        until = time.monotonic()+args.wait_seconds
        while True:
            receipt = files.receipt(request)
            if receipt is not None: return receipt.model_dump(mode='json')
            remaining = until-time.monotonic()
            if remaining <= 0:
                # Pending is explicit. A successful local write is not acceptance.
                return {'request_id':request.request_id, 'status':'receipt_pending'}
            time.sleep(min(0.1,remaining))
