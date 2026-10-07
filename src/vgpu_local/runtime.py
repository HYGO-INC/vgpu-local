"""Browser-independent reconciliation. All engine creates require a durable claim."""
import asyncio
from contextlib import suppress

from .comfyui import EngineError
from .runtime_store import TERMINAL


class Runtime:
    def __init__(self, store, engine, *, cloud=None, cloud_identity=None, interval=1):
        self.store, self.engine, self.cloud = store, engine, cloud
        self.cloud_identity, self.interval = cloud_identity, interval
        self.cloud_state = "disabled" if cloud is None else "connecting"
        self.stopping = asyncio.Event()

    def step(self):
        for job in self.store.jobs(active=True):
            try:
                claimed = self.store.claim_submission(job["execution_id"])
                if claimed:
                    job = claimed
                    changes = self.engine.submit(job)
                else:
                    changes = self.engine.observe(job)
                    if job["cancel_requested"] and changes["state"] not in TERMINAL:
                        # First prove that the engine job is ours; missing evidence
                        # cannot authorize canceling an unrelated/reused identifier.
                        if changes["state"] in {"queued", "running"}:
                            self.engine.cancel(job)
                        changes["state"] = "cancel_requested"
                self.store.update(job["execution_id"], job["revision"], **changes)
            except EngineError as error:
                self.store.update(job["execution_id"], job["revision"],
                                  state="cancel_requested" if job["cancel_requested"] else "uncertain",
                                  error_code=str(error))

    def exchange(self):
        # Enrollment/config changes cannot redirect an existing site's report outbox.
        settings = self.cloud.settings()
        if {k: settings[k] for k in self.cloud_identity} != self.cloud_identity:
            raise ValueError("runtime_cloud_identity_changed")
        batch = self.store.exchange_batch()
        response = self.cloud.exchange(batch)
        self.store.acknowledge(batch, response)
        scope = {k: settings[k] for k in ("tenant_id", "project_id", "site_id")}
        for command in response["commands"]:
            self.store.accept(command, scope, origin="cloud")
        self.cloud_state = "connected"

    async def loop(self, action, *, cloud=False):
        while not self.stopping.is_set():
            if cloud:
                try:
                    await asyncio.to_thread(action)
                except (RuntimeError, ValueError, OSError):
                    self.cloud_state = "unavailable"
            else:
                await asyncio.to_thread(action)
            with suppress(TimeoutError):
                await asyncio.wait_for(self.stopping.wait(), self.interval)

    async def run(self):
        # A cloud timeout must not stall local observation or execution.
        async with asyncio.TaskGroup() as group:
            group.create_task(self.loop(self.step))
            if self.cloud: group.create_task(self.loop(self.exchange, cloud=True))
