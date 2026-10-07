"""Durable owner-local execution intent; engine queues remain the scheduler."""
import json
from pathlib import Path
import re
import time
from uuid import UUID, uuid4

from .contracts.models import LocalExecutionCommand, LocalCommandReceipt, LocalExecutionReport
from .journal import Journal, fingerprint
from .errors import KeyConflict

TERMINAL = {"succeeded", "failed", "canceled"}


class RuntimeStore:
    def __init__(self, path: Path, *, create=False):
        self.journal = Journal(path, create=create)
        with self.journal.connection() as db:
            if create:
                statements = """
                CREATE TABLE IF NOT EXISTS runtime_jobs (id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runtime_recipes (id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runtime_commands
                  (id TEXT PRIMARY KEY, digest TEXT NOT NULL, data TEXT NOT NULL,
                   origin TEXT NOT NULL, uploaded INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS runtime_reports
                  (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, data TEXT NOT NULL,
                   uploaded INTEGER NOT NULL DEFAULT 0);
                """
                for statement in statements.split(';'):
                    if statement.strip(): db.execute(statement)
            else:
                for name in ("runtime_jobs", "runtime_recipes", "runtime_commands", "runtime_reports"):
                    db.execute(f"SELECT id FROM {name} LIMIT 0")

    def install_recipe(self, recipe_id, title, prompt):
        if not isinstance(recipe_id, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", recipe_id):
            raise ValueError("invalid_recipe_id")
        if not isinstance(title, str) or not 1 <= len(title) <= 120:
            raise ValueError("invalid_recipe_title")
        if not isinstance(prompt, dict) or not prompt or len(prompt) > 2000:
            raise ValueError("api_format_workflow_required")
        if len(json.dumps(prompt).encode()) > 1_000_000:
            raise ValueError("workflow_too_large")
        if any(not isinstance(node, dict) or not isinstance(node.get("class_type"), str)
               or not isinstance(node.get("inputs"), dict) for node in prompt.values()):
            raise ValueError("api_format_workflow_required")
        recipe = dict(recipe_id=recipe_id, title=title, recipe_sha256=fingerprint(prompt), prompt=prompt)
        with self.journal.connection() as db:
            db.execute("INSERT INTO runtime_recipes VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                       (recipe_id, json.dumps(recipe)))
        return {k: v for k, v in recipe.items() if k != "prompt"}

    def recipes(self):
        with self.journal.connection() as db:
            return [{k: v for k, v in json.loads(row[0]).items() if k != "prompt"}
                    for row in db.execute("SELECT data FROM runtime_recipes ORDER BY id")]

    def local_command(self, installation_id, action, recipe_id, *, execution_id=None):
        if action not in {"start", "cancel"}: raise ValueError("invalid_command_action")
        scope = dict(tenant_id="local", project_id="local", site_id=installation_id)
        if action == "start":
            recipe = next((r for r in self.recipes() if r["recipe_id"] == recipe_id), None)
            if recipe is None: raise ValueError("recipe_not_installed")
            generation = 1
        else:
            job = self.job(execution_id)
            # Local owner cancellation keeps the original scope, including cloud jobs.
            scope = job["scope"]
            recipe = job
            recipe_id = job["recipe_id"]
            generation = job["generation"] + 1
        command = dict(command_id="cmd_"+uuid4().hex, **scope,
                       execution_id=execution_id or "lex_"+uuid4().hex, generation=generation,
                       expires_at=int(time.time())+300, action=action, recipe_id=recipe_id,
                       recipe_sha256=recipe["recipe_sha256"])
        command["request_sha256"] = fingerprint(command)
        return command

    def accept(self, document, expected_scope, *, origin, now=None):
        if origin not in {"local", "cloud"}: raise ValueError("invalid_command_origin")
        command = LocalExecutionCommand.model_validate(document).model_dump()
        scope = {k: command[k] for k in ("tenant_id", "project_id", "site_id")}
        if scope != expected_scope: raise ValueError("command_scope_mismatch")
        digest = fingerprint({k: v for k, v in command.items() if k != "request_sha256"})
        if command["request_sha256"] != digest: raise ValueError("command_digest_mismatch")
        now = int(time.time()) if now is None else now
        with self.journal.connection() as db:
            previous = db.execute("SELECT * FROM runtime_commands WHERE id=?", (command["command_id"],)).fetchone()
            if previous:
                if previous["digest"] != digest: raise KeyConflict("command_identity_conflict")
                return json.loads(previous["data"])
            receipt = dict(command_id=command["command_id"], request_sha256=digest, accepted=True)
            row = db.execute("SELECT data FROM runtime_jobs WHERE id=?", (command["execution_id"],)).fetchone()
            job = json.loads(row[0]) if row else None
            recipe_row = db.execute("SELECT data FROM runtime_recipes WHERE id=?", (command["recipe_id"],)).fetchone()
            recipe = json.loads(recipe_row[0]) if recipe_row else None
            error = None
            if command["expires_at"] <= now: error = "command_expired"
            elif job and (job["scope"] != scope or any(job[k] != command[k] for k in ("recipe_id", "recipe_sha256"))):
                error = "execution_identity_conflict"
            elif job and command["generation"] <= job["generation"]: error = "stale_generation"
            elif command["action"] == "start" and job: error = "execution_already_exists"
            elif command["action"] == "start" and (not recipe or recipe["recipe_sha256"] != command["recipe_sha256"]):
                error = "recipe_not_approved"
            if error:
                receipt.update(accepted=False, error_code=error)
            else:
                if job is None:
                    job = dict(execution_id=command["execution_id"], scope=scope, origin=origin,
                               recipe_id=command["recipe_id"], recipe_sha256=command["recipe_sha256"],
                               prompt=recipe["prompt"] if recipe else {}, generation=0, revision=0,
                               engine_job_id=str(UUID(command["execution_id"][4:])),
                               submission_started=False, cancel_requested=False, state="accepted",
                               correlation=uuid4().hex, outputs={})
                job["generation"] = command["generation"]
                if command["action"] == "cancel":
                    job["cancel_requested"] = True
                    if job["state"] not in TERMINAL:
                        job["state"] = "cancel_requested" if job["submission_started"] else "canceled"
                self._save(db, job)
            LocalCommandReceipt.model_validate(receipt)
            db.execute("INSERT INTO runtime_commands(id,digest,data,origin) VALUES(?,?,?,?)",
                       (command["command_id"], digest, json.dumps(receipt), origin))
            return receipt

    def job(self, execution_id):
        with self.journal.connection() as db:
            row = db.execute("SELECT data FROM runtime_jobs WHERE id=?", (execution_id,)).fetchone()
            if row is None: raise ValueError("execution_not_found")
            return json.loads(row[0])

    def jobs(self, *, active=False):
        with self.journal.connection() as db:
            query = ("SELECT data FROM runtime_jobs WHERE json_extract(data,'$.state') "
                     "NOT IN ('succeeded','failed','canceled') ORDER BY rowid" if active else
                     "SELECT data FROM runtime_jobs ORDER BY rowid DESC LIMIT 500")
            return [json.loads(row[0]) for row in db.execute(query)]

    def claim_submission(self, execution_id):
        with self.journal.connection() as db:
            row = db.execute("SELECT data FROM runtime_jobs WHERE id=?", (execution_id,)).fetchone()
            job = json.loads(row[0])
            if job["submission_started"] or job["state"] != "accepted" or job["cancel_requested"]: return None
            job.update(submission_started=True, state="dispatching")
            self._save(db, job)
            return job

    def update(self, execution_id, revision, **changes):
        with self.journal.connection() as db:
            row = db.execute("SELECT data FROM runtime_jobs WHERE id=?", (execution_id,)).fetchone()
            job = json.loads(row[0])
            if job["revision"] != revision or job["state"] in TERMINAL: return False
            if all(job.get(k) == value for k, value in changes.items()): return True
            job.update(changes)
            self._save(db, job)
            return True

    def _save(self, db, job):
        job["revision"] += 1
        db.execute("INSERT INTO runtime_jobs VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                   (job["execution_id"], json.dumps(job)))
        report = self.report(job)
        if job["origin"] == "cloud":
            db.execute("INSERT INTO runtime_reports VALUES(?,?,?,0) ON CONFLICT(id) DO UPDATE SET "
                       "revision=excluded.revision,data=excluded.data,uploaded=0",
                       (job["execution_id"], job["revision"], json.dumps(report)))

    @staticmethod
    def report(job):
        value = {k: job[k] for k in ("execution_id", "revision", "generation", "state", "recipe_id", "recipe_sha256")}
        if job.get("error_code"): value["error_code"] = job["error_code"]
        return LocalExecutionReport.model_validate(value).model_dump()

    def exchange_batch(self):
        with self.journal.connection() as db:
            return dict(receipts=[json.loads(row[0]) for row in db.execute(
                "SELECT data FROM runtime_commands WHERE origin='cloud' AND uploaded=0 ORDER BY rowid LIMIT 20")],
                reports=[json.loads(row[0]) for row in db.execute(
                "SELECT data FROM runtime_reports WHERE uploaded=0 ORDER BY rowid LIMIT 20")])

    def acknowledge(self, sent, response):
        commands = {c["command_id"] for c in sent["receipts"]}
        reports = {(r["execution_id"], r["revision"]) for r in sent["reports"]}
        if (not set(response["command_receipts"]) <= commands or
                not {(r["execution_id"], r["revision"]) for r in response["report_receipts"]} <= reports):
            raise ValueError("unexpected_exchange_acknowledgement")
        with self.journal.connection() as db:
            for command_id in response["command_receipts"]:
                db.execute("UPDATE runtime_commands SET uploaded=1 WHERE id=?", (command_id,))
            for report in response["report_receipts"]:
                db.execute("UPDATE runtime_reports SET uploaded=1 WHERE id=? AND revision=?",
                           (report["execution_id"], report["revision"]))
