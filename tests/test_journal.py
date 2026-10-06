from concurrent.futures import ThreadPoolExecutor

import pytest

from vgpu_local.journal import Journal, fingerprint
from vgpu_local.errors import KeyConflict


def test_receipt_claim_and_updates_are_atomic_across_connections(tmp_path):
    path = tmp_path / "receipts.sqlite"
    journal = Journal(path)
    key = fingerprint({"operation": "one"})

    def worker(_):
        independent = Journal(path)
        inserted, _ = independent.begin(key, {"request": "same"}, {"state": "pending", "count": 0})
        independent.change(key, lambda row: {**row, "count": row["count"] + 1})
        claimed, _ = independent.transition(key, "pending", "creating")
        return inserted, claimed

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(worker, range(32)))
    assert sum(inserted for inserted, _ in results) == 1
    assert sum(claimed for _, claimed in results) == 1
    assert journal.read(key) == {"state": "creating", "count": 32}


def test_failed_receipt_change_and_conflict_preserve_original(tmp_path):
    journal = Journal(tmp_path / "receipts.sqlite")
    journal.begin("key", {"gpu": 1}, {"state": "allocated"})

    def fail(row):
        row["state"] = "released"
        raise RuntimeError("interrupted transaction")

    with pytest.raises(RuntimeError):
        journal.change("key", fail)
    with pytest.raises(KeyConflict):
        journal.begin("key", {"gpu": 2}, {"state": "released"})
    assert Journal(tmp_path / "receipts.sqlite").read("key") == {"state": "allocated"}
