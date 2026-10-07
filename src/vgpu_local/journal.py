"""Single-site durable operation receipts; cloud financial state lives elsewhere."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Callable, Protocol

import rfc8785

from .errors import KeyConflict


class ReceiptStore(Protocol):
    """Atomic backend receipt boundary; shared services may supply another store.

    begin must commit before returning a winning create claim. change must lock
    the receipt until its transaction commits. A missing read is KeyError;
    connection failures and malformed receipts must never be reported as missing.
    Receipts must not expire while an allocation can still exist.
    """
    def begin(self, key: str, request: dict, initial: dict) -> tuple[bool, dict]: ...
    def read(self, key: str) -> dict: ...
    def change(self, key: str, update: Callable[[dict], dict]) -> dict: ...
    def transition(self, key: str, expected: str, state: str) -> tuple[bool, dict]: ...


def fingerprint(value: dict) -> str:
    return hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def scope(request) -> str:
    return fingerprint({key: getattr(request, key) for key in (
        "tenant_id", "project_id", "account_id", "provider", "operation_id", "generation")})


class Journal:
    def __init__(self, path: str | Path, *, create: bool = True):
        self.path = str(path)
        self.existing_only = not create
        with self.connection() as db:
            if create:
                db.execute("""CREATE TABLE IF NOT EXISTS operations (
                    scope TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                    receipt TEXT NOT NULL
                )""")
            else:
                db.execute("SELECT scope,fingerprint,receipt FROM operations LIMIT 0")

    @contextmanager
    def connection(self):
        target = Path(self.path).resolve().as_uri()+"?mode=rw" if self.existing_only else self.path
        db = sqlite3.connect(target, uri=self.existing_only, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA busy_timeout=30000")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def begin(self, key: str, request: dict, initial: dict) -> tuple[bool, dict]:
        digest = fingerprint(request)
        with self.connection() as db:
            row = db.execute("SELECT * FROM operations WHERE scope=?", (key,)).fetchone()
            if row:
                if row["fingerprint"] != digest:
                    raise KeyConflict("operation identity is already bound to another request")
                return False, json.loads(row["receipt"])
            db.execute("INSERT INTO operations VALUES (?, ?, ?)", (key, digest, json.dumps(initial)))
        return True, initial

    def read(self, key: str) -> dict:
        with self.connection() as db:
            row = db.execute("SELECT receipt FROM operations WHERE scope=?", (key,)).fetchone()
            if row is None:
                raise KeyError(key)
            return json.loads(row["receipt"])

    def change(self, key: str, update) -> dict:
        with self.connection() as db:
            row = db.execute("SELECT receipt FROM operations WHERE scope=?", (key,)).fetchone()
            if row is None:
                raise KeyError(key)
            receipt = update(json.loads(row["receipt"]))
            db.execute("UPDATE operations SET receipt=? WHERE scope=?", (json.dumps(receipt), key))
            return receipt

    def transition(self, key: str, expected: str, state: str) -> tuple[bool, dict]:
        claimed = False
        def update(row):
            nonlocal claimed
            if row["state"] == expected:
                row["state"] = state
                claimed = True
            return row
        receipt = self.change(key, update)
        return claimed, receipt
