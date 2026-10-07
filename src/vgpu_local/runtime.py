"""Browser-independent reconciliation. All engine creates require a durable claim."""
import asyncio
import time
from contextlib import suppress

from .comfyui import EngineError
from .journal import fingerprint
from .runtime_store import TERMINAL


class Runtime:
    def __init__(self, store, engine, *, cloud=None, cloud_identity=None, interval=1,
                 wall_clock=time.time, monotonic=time.monotonic):
        self.store, self.engine, self.cloud = store, engine, cloud
        if cloud is not None and (cloud_identity is None or set(cloud_identity) !=
                                  {"endpoint", "tenant_id", "project_id", "site_id"}):
            raise ValueError("runtime_cloud_identity_required")
        self.cloud_identity = dict(cloud_identity) if cloud_identity is not None else None
        self.interval = interval
        self.wall_clock, self.monotonic = wall_clock, monotonic
        self.maintenance_after = 0
        # Digest of the recipe catalog the service last reported holding.
        self.hosted_recipes = None
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
        if self.monotonic() >= self.maintenance_after:
            self.cloud.maintain(now=self.wall_clock(), expected_identity=self.cloud_identity)
            # A failed or interrupted renewal remains due. Restarts check promptly;
            # wall-clock adjustments cannot suppress future maintenance checks.
            self.maintenance_after = self.monotonic() + 3600
        batch = self.store.exchange_batch()
        # The catalog travels only when it differs from the service's copy, so a
        # restarted runtime or a service that lost it converges on the next call.
        catalog = self.store.startable_recipes()
        if fingerprint(catalog) != self.hosted_recipes:
            batch = dict(batch, recipes=catalog)
        response = self.cloud.exchange(batch, expected_identity=self.cloud_identity)
        self.store.acknowledge(batch, response)
        self.hosted_recipes = response.get("recipes_sha256")
        scope = {k: self.cloud_identity[k] for k in ("tenant_id", "project_id", "site_id")}
        for command in response["commands"]:
            self.store.accept(command, scope, origin="cloud")
        self.cloud_state = "connected"

    async def loop(self, action, *, cloud=False):
        delay = self.interval
        while not self.stopping.is_set():
            if cloud:
                try:
                    await asyncio.to_thread(action)
                    delay = self.interval
                except (RuntimeError, ValueError, OSError):
                    self.cloud_state = "unavailable"
                    delay = min(max(delay * 2, 5), 60)
            else:
                await asyncio.to_thread(action)
            with suppress(TimeoutError):
                await asyncio.wait_for(self.stopping.wait(), delay)

    async def run(self):
        # A cloud timeout must not stall local observation or execution.
        async with asyncio.TaskGroup() as group:
            group.create_task(self.loop(self.step))
            if self.cloud: group.create_task(self.loop(self.exchange, cloud=True))
