"""Linux file transport for one authenticated interruption participant.

The installer owns the parent directory, snapshot and receipts. It gives the
workload write access only to requests/. Pinning directory descriptors and using
O_NOFOLLOW keeps malicious request paths outside the publisher's filesystem.
"""
from contextlib import ExitStack
import itertools
import json
import os
from pathlib import Path
import re
import stat
import sys
from uuid import uuid4

import rfc8785

from .contracts.models import InterruptionReceipt, InterruptionRequest, InterruptionScope, InterruptionSnapshot
from .errors import KeyConflict
from .interruptions import InterruptionController
from .journal import fingerprint

MESSAGE_LIMIT = 32768
SNAPSHOT_LIMIT = 2 * 1024 * 1024
REQUEST_NAME = re.compile(r"irq_[a-f0-9]{32}\.json")


class InterruptionFiles:
    def __init__(self, root: Path, scope: InterruptionScope, participant_id: str, *, create: bool = False):
        if sys.platform != "linux": raise OSError("interruption file transport requires Linux/WSL")
        if not isinstance(participant_id,str) or not 1 <= len(participant_id) <= 255: raise ValueError("invalid participant")
        self.scope, self.participant_id = scope, participant_id
        self.cursor, self.snapshot_fingerprint = -1, None
        self.stack = ExitStack()
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            if create: root.mkdir(mode=0o750,parents=False,exist_ok=True)
            self.root = os.open(root,flags)
            self.stack.callback(os.close,self.root)
            for directory in ("requests","receipts"):
                if create:
                    try: os.mkdir(directory,mode=0o700,dir_fd=self.root)
                    except FileExistsError: pass
                descriptor = os.open(directory,flags,dir_fd=self.root)
                self.stack.callback(os.close,descriptor)
                setattr(self,directory,descriptor)
        except BaseException:
            self.stack.close()
            raise

    def __enter__(self): return self
    def __exit__(self,*args): self.stack.close()

    def _bound(self, document):
        if {key:getattr(document,key) for key in InterruptionScope.model_fields} != self.scope.model_dump():
            raise PermissionError("file belongs to another runtime")
        if hasattr(document,"participant_id") and document.participant_id != self.participant_id:
            raise PermissionError("file belongs to another participant")

    def publish(self, snapshot: InterruptionSnapshot):
        """Publisher-only port; workloads must have no write access here."""
        snapshot = InterruptionSnapshot.model_validate(snapshot.model_dump())
        self._bound(snapshot)
        for notice in snapshot.interruptions: self._bound(notice)
        self._write(self.root,"state.json",snapshot.model_dump(mode="json"),SNAPSHOT_LIMIT,replace=True)

    def snapshot(self) -> InterruptionSnapshot:
        snapshot = InterruptionSnapshot.model_validate(self._read(self.root,"state.json",SNAPSHOT_LIMIT))
        self._bound(snapshot)
        for notice in snapshot.interruptions: self._bound(notice)
        digest = fingerprint(snapshot.model_dump(mode="json"))
        if snapshot.cursor < self.cursor or (snapshot.cursor == self.cursor and digest != self.snapshot_fingerprint):
            raise ValueError("snapshot cursor moved backwards or was reused")
        self.cursor, self.snapshot_fingerprint = snapshot.cursor,digest
        return snapshot

    def submit(self, request: InterruptionRequest):
        """Durable local submission only. Call receipt to obtain server acceptance."""
        request = InterruptionRequest.model_validate(request.model_dump())
        self._bound(request)
        self._write(self.requests,request.request_id+".json",request.model_dump(mode="json"),MESSAGE_LIMIT,replace=False)

    def receipt(self, request: InterruptionRequest) -> InterruptionReceipt | None:
        request = InterruptionRequest.model_validate(request.model_dump())
        self._bound(request)
        try: document = self._read(self.receipts,request.request_id+".json",MESSAGE_LIMIT)
        except FileNotFoundError: return None
        receipt = InterruptionReceipt.model_validate(document)
        self._bound(receipt)
        if (receipt.request_id != request.request_id or receipt.interruption_id != request.interruption_id
                or receipt.action != request.action or receipt.request_fingerprint != "sha256:"+fingerprint(request.model_dump(mode="json"))):
            raise ValueError("receipt does not acknowledge this exact request")
        return receipt

    def forward(self, controller: InterruptionController, *, limit: int = 64) -> dict[str,int]:
        """Publisher-only: process a bounded spool batch using the bound identity.

        Unexpected controller/store failures leave the request for a retry.
        Invalid files stay unacknowledged and are reported for local inspection.
        One participant's directory is never used as another participant's queue.
        """
        if controller.scope != self.scope or self.participant_id not in controller.participants:
            raise PermissionError("forwarder does not own this runtime/participant")
        if type(limit) is not int or not 1 <= limit <= 256: raise ValueError("invalid batch limit")
        processed,invalid = 0,0
        with os.scandir(self.requests) as entries:
            for entry in itertools.islice(entries,limit):
                if not REQUEST_NAME.fullmatch(entry.name):
                    invalid += 1
                    continue
                try:
                    request = InterruptionRequest.model_validate(self._read(self.requests,entry.name,MESSAGE_LIMIT))
                    self._bound(request)
                    if request.request_id+".json" != entry.name: raise ValueError("filename identity mismatch")
                except (OSError,ValueError,PermissionError):
                    invalid += 1
                    continue
                try: receipt = controller.respond(request,participant_id=self.participant_id)
                except KeyConflict:
                    invalid += 1
                    continue
                self._write(self.receipts,entry.name,receipt.model_dump(mode="json"),MESSAGE_LIMIT,replace=True)
                # Unlinking by a pinned directory descriptor can only remove a
                # spool entry. It cannot follow a substituted symlink target.
                try: os.unlink(entry.name,dir_fd=self.requests)
                except FileNotFoundError: pass
                processed += 1
        if processed: os.fsync(self.requests)
        return {"processed":processed,"invalid":invalid}

    @staticmethod
    def _read(directory, name, maximum):
        fd = os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=directory)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > maximum: raise ValueError("untrusted file type or size")
            content = bytearray()
            while len(content) <= maximum:
                chunk = os.read(fd,min(65536,maximum+1-len(content)))
                if not chunk: break
                content.extend(chunk)
            if len(content) > maximum: raise ValueError("file grew beyond its bound")
            def unique_pairs(pairs):
                result = {}
                for key,value in pairs:
                    if key in result: raise ValueError("duplicate JSON property")
                    result[key] = value
                return result
            def invalid_constant(value): raise ValueError("non-JSON numeric constant")
            try: return json.loads(content,object_pairs_hook=unique_pairs,parse_constant=invalid_constant)
            except RecursionError as error: raise ValueError("JSON nesting exceeds parser bounds") from error
        finally: os.close(fd)

    @classmethod
    def _write(cls,directory,name,document,maximum,*,replace):
        content = rfc8785.dumps(document)
        if len(content) > maximum: raise ValueError("message exceeds transport bound")
        temporary = ".vgpu-"+uuid4().hex+".tmp"
        fd = os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o640,dir_fd=directory)
        try:
            with os.fdopen(fd,"wb") as file:
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            if replace:
                os.replace(temporary,name,src_dir_fd=directory,dst_dir_fd=directory)
            else:
                try: os.link(temporary,name,src_dir_fd=directory,dst_dir_fd=directory,follow_symlinks=False)
                except FileExistsError:
                    previous = cls._read(directory,name,maximum)
                    if fingerprint(previous) != fingerprint(document): raise KeyConflict("request file already contains another intent")
            os.fsync(directory)
        finally:
            try: os.unlink(temporary,dir_fd=directory)
            except FileNotFoundError: pass
