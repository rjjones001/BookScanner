"""Tiny SQLite job store (swap for PostgreSQL in production - see docs/ARCHITECTURE.md)."""
from __future__ import annotations
import json
import sqlite3
import threading
import time
from . import config

_lock = threading.Lock()


def _conn():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(config.DATA_DIR / "jobs.sqlite3", timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init():
    with _lock, _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS jobs(
            id TEXT PRIMARY KEY, owner TEXT, filename TEXT, status TEXT, stage TEXT, params TEXT,
            pages_total INT DEFAULT 0, pages_done INT DEFAULT 0, pages_failed INT DEFAULT 0,
            warnings TEXT DEFAULT '[]', error TEXT DEFAULT '', cancel INT DEFAULT 0,
            created REAL, updated REAL)""")


def create(job_id, owner, filename, params, pages_total):
    with _lock, _conn() as c:
        c.execute("INSERT INTO jobs(id,owner,filename,status,stage,params,pages_total,created,updated) "
                  "VALUES(?,?,?,?,?,?,?,?,?)",
                  (job_id, owner, filename, "queued", "queued", json.dumps(params), pages_total,
                   time.time(), time.time()))


def update(job_id, **kw):
    if "warnings" in kw:
        kw["warnings"] = json.dumps(kw["warnings"])
    kw["updated"] = time.time()
    cols = ",".join(f"{k}=?" for k in kw)
    with _lock, _conn() as c:
        c.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*kw.values(), job_id))


def incr(job_id, field):
    assert field in ("pages_done", "pages_failed")
    with _lock, _conn() as c:
        c.execute(f"UPDATE jobs SET {field}={field}+1, updated=? WHERE id=?", (time.time(), job_id))


def _row(r):
    if not r:
        return None
    d = dict(r)
    d["params"] = json.loads(d["params"])
    d["warnings"] = json.loads(d["warnings"])
    return d


def get(job_id, owner=None):
    with _lock, _conn() as c:
        r = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    d = _row(r)
    return d if d and (owner is None or d["owner"] == owner) else None


def list_for(owner):
    with _lock, _conn() as c:
        rows = c.execute("SELECT * FROM jobs WHERE owner=? ORDER BY created DESC", (owner,)).fetchall()
    return [_row(r) for r in rows]


def delete(job_id):
    with _lock, _conn() as c:
        c.execute("DELETE FROM jobs WHERE id=?", (job_id,))


def expired(cutoff):
    with _lock, _conn() as c:
        return [r["id"] for r in c.execute("SELECT id FROM jobs WHERE created<?", (cutoff,))]
