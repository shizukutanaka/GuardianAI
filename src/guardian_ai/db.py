"""ShieldAI Database - SQLite schema and initialization"""
import hashlib
import hmac
import sqlite3

from guardian_ai.paths import data_dir

DB_PATH = str(data_dir() / "shield_ai.db")

AGENTS = [
    ("accounting", "llama3:8b"),
    ("legal", "llama3:8b"),
    ("hr", "llama3:8b"),
    ("it", "llama3:8b"),
    ("developer", "llama3:8b"),
    ("medical", "llama3:8b"),
    ("general", "llama3:8b"),
]


def init_database(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Initialize schema, seed agents, and return an open connection."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            model TEXT NOT NULL,
            complexity TEXT DEFAULT 'medium',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent TEXT NOT NULL,
            request TEXT NOT NULL,
            result TEXT NOT NULL,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
            latency_ms INTEGER,
            chain_hash TEXT,
            FOREIGN KEY (agent) REFERENCES agents (name)
        )
    """)

    _migrate_chain_hash(conn)
    # append-only triggers are dropped at init start so migrations can
    # still write (re-signed below); they are re-created at init end.
    conn.execute("DROP TRIGGER IF EXISTS audit_no_update")
    conn.execute("DROP TRIGGER IF EXISTS audit_no_delete")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chain_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            row_count INTEGER NOT NULL,
            head TEXT NOT NULL,
            state_hmac TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent TEXT NOT NULL,
            priority TEXT DEFAULT 'medium',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS task_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            agent TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            priority TEXT DEFAULT 'medium',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES tasks (id)
        )
    """)

    c.executemany(
        "INSERT OR IGNORE INTO agents (name, model) VALUES (?, ?)", AGENTS)

    _resign_legacy_chain(conn)
    _backfill_chain(conn)
    _resync_chain_state(conn)
    # append-only layer: block UPDATE/DELETE on audit_logs. Stops naive
    # edits and bugs (an attacker who owns the file can drop triggers,
    # which is why the keyed chain below is the real integrity check).
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS audit_no_update
        BEFORE UPDATE ON audit_logs
        BEGIN SELECT RAISE(ABORT, 'audit_logs is append-only'); END
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS audit_no_delete
        BEFORE DELETE ON audit_logs
        BEGIN SELECT RAISE(ABORT, 'audit_logs is append-only'); END
    """)
    conn.commit()

    conn.commit()
    return conn


def _chain_hash(prev: str, agent: str, request: str, result: str,
                timestamp: str) -> str:
    """HMAC(key, prev + row fields) over the chain. A bare hash can be
    recomputed by anyone with DB access (forgeable); a keyed MAC needs the
    KMS key, which lives outside the DB (DPAPI-protected), so an attacker
    who can only write rows cannot re-sign a forged chain."""
    from guardian_ai.kms import get_key
    body = f"{prev}|{agent}|{request}|{result}|{timestamp}"
    return hmac.new(get_key("audit_chain"), body.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def _legacy_chain_hash(prev: str, agent: str, request: str, result: str,
                       timestamp: str) -> str:
    """The original bare-sha256 chain algo, kept only to detect intact
    legacy chains during migration."""
    body = f"{prev}|{agent}|{request}|{result}|{timestamp}"
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _resign_legacy_chain(conn: sqlite3.Connection) -> None:
    """If every stored chain_hash still matches the *legacy* bare-sha256
    chain, the row data is intact but forgeable - re-sign the whole chain
    with the keyed HMAC. A chain matching neither algo is left alone
    (verify_audit_chain will honestly report it as broken)."""
    rows = conn.execute(
        "SELECT id, agent, request, result, timestamp, chain_hash "
        "FROM audit_logs ORDER BY id").fetchall()
    if not rows:
        return
    prev, legacy_ok = "", True
    for rid, agent, req, res, ts, stored in rows:
        if stored != _legacy_chain_hash(prev, agent, req, res, ts):
            legacy_ok = False
            break
        prev = stored
    if not legacy_ok:
        return  # already HMAC (verify will pass) or genuinely tampered
    prev = ""
    for rid, agent, req, res, ts, stored in rows:
        h = _chain_hash(prev, agent, req, res, ts)
        conn.execute("UPDATE audit_logs SET chain_hash = ? WHERE id = ?",
                     (h, rid))
        prev = h
    conn.commit()


def _migrate_chain_hash(conn: sqlite3.Connection) -> None:
    """Add chain_hash column to DBs created before it existed."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(audit_logs)")}
    if "chain_hash" not in cols:
        conn.execute("ALTER TABLE audit_logs ADD COLUMN chain_hash TEXT")
        conn.commit()
    if "latency_ms" not in cols:
        conn.execute("ALTER TABLE audit_logs ADD COLUMN latency_ms INTEGER")
        conn.commit()


def _backfill_chain(conn: sqlite3.Connection) -> None:
    """Hash existing rows (id order). Pre-chain rows become the trusted
    baseline - only NEW tampering can be detected, which is honest."""
    rows = conn.execute(
        "SELECT id, agent, request, result, timestamp, chain_hash "
        "FROM audit_logs ORDER BY id").fetchall()
    prev = ""
    dirty = False
    for rid, agent, req, res, ts, existing in rows:
        if existing:
            prev = existing
            continue
        h = _chain_hash(prev, agent, req, res, ts)
        conn.execute("UPDATE audit_logs SET chain_hash = ? WHERE id = ?",
                     (h, rid))
        prev = h
        dirty = True
    if dirty:
        conn.commit()


def _state_hmac(row_count: int, head: str) -> str:
    """Keyed MAC over the authenticated chain head+count. Deleting the
    newest rows leaves a valid chain but a stale state -> detected."""
    from guardian_ai.kms import get_key
    return hmac.new(get_key("audit_chain"),
                    f"{row_count}|{head}".encode("utf-8"),
                    hashlib.sha256).hexdigest()


def _update_chain_state(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT COUNT(*), (SELECT chain_hash FROM audit_logs "
        "ORDER BY id DESC LIMIT 1) FROM audit_logs").fetchone()
    conn.execute(
        "INSERT INTO chain_state (id, row_count, head, state_hmac) "
        "VALUES (1, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
        "row_count=excluded.row_count, head=excluded.head, "
        "state_hmac=excluded.state_hmac",
        (row[0], row[1] or "", _state_hmac(row[0], row[1] or "")))
    conn.commit()


def _resync_chain_state(conn: sqlite3.Connection) -> None:
    """Create or repair chain_state from intact rows (init-time)."""
    _update_chain_state(conn)


def audit_log(conn: sqlite3.Connection, agent: str, request: str,
              result: str, latency_ms: int = None) -> int:
    """Append one entry to audit_logs, commit, and return its row id."""
    prev_row = conn.execute(
        "SELECT chain_hash FROM audit_logs ORDER BY id DESC LIMIT 1").fetchone()
    prev = prev_row[0] if prev_row and prev_row[0] else ""
    ts = conn.execute("SELECT CURRENT_TIMESTAMP").fetchone()[0]
    h = _chain_hash(prev, agent, request, result, ts)
    cur = conn.execute(
        "INSERT INTO audit_logs (agent, request, result, timestamp, "
        "latency_ms, chain_hash) VALUES (?, ?, ?, ?, ?, ?)",
        (agent, request, result, ts, latency_ms, h))
    conn.commit()
    _update_chain_state(conn)
    return cur.lastrowid


def verify_audit_chain(conn: sqlite3.Connection) -> dict:
    """Recompute the whole chain + the authenticated head. Returns
    {'ok': bool, 'broken_at': id|None}. The chain_state check catches
    truncation: deleting the newest rows leaves a valid-looking chain but
    a stale count/head that only the key-holder could update."""
    rows = conn.execute(
        "SELECT id, agent, request, result, timestamp, chain_hash "
        "FROM audit_logs ORDER BY id").fetchall()
    prev = ""
    for rid, agent, req, res, ts, stored in rows:
        if stored is None:
            return {"ok": False, "broken_at": rid, "reason": "missing chain_hash"}
        expect = _chain_hash(prev, agent, req, res, ts)
        if expect != stored:
            return {"ok": False, "broken_at": rid,
                    "reason": "row content or chain_hash was modified"}
        prev = stored
    state = conn.execute(
        "SELECT row_count, head, state_hmac FROM chain_state "
        "WHERE id = 1").fetchone()
    if state:
        scount, shead, shmac = state
        if shmac != _state_hmac(scount, shead):
            return {"ok": False, "broken_at": None,
                    "reason": "chain_state signature invalid"}
        if scount != len(rows) or shead != (prev or ""):
            return {"ok": False, "broken_at": None,
                    "reason": "tail rows deleted or head replaced"}
    return {"ok": True, "broken_at": None, "entries": len(rows)}


def record_tasks(conn: sqlite3.Connection, agent: str, complexity: str,
                 steps: list, execution_steps: list = None) -> None:
    """Persist plan steps into tasks + task_queue.

    `execution_steps` (Executor's step outcomes) supply real statuses;
    without them every step is assumed 'done'."""
    priority = "high" if complexity == "complex" else "medium"
    normalize = {"ok": "done", "fail": "failed",
                 "blocked": "blocked", "partial": "failed",
                 "redacted": "done"}
    status_by_type = {}
    for s in execution_steps or []:
        status_by_type.setdefault(
            s.get("step"), normalize.get(s.get("status"), "done"))
    for step in steps:
        stype = step.get("type")
        if stype == "audit":
            status = "done"  # this record itself is the audit trail
        elif execution_steps is None:
            status = "done"  # no execution info; assume the plan ran
        else:
            status = status_by_type.get(stype, "skipped")
            # 'skipped' is honest when a gate (e.g. PHI) stopped the run
        cur = conn.execute(
            "INSERT INTO tasks (agent, priority) VALUES (?, ?)", (agent, priority))
        conn.execute(
            "INSERT INTO task_queue (task_id, agent, status, priority) "
            "VALUES (?, ?, ?, ?)", (cur.lastrowid, agent, status, priority))
    conn.commit()


def export_audit(conn: sqlite3.Connection, limit: int = 100,
                 out_dir: str = None) -> str:
    """Export the newest `limit` audit entries as an AES-256-GCM file.

    Requires the `cryptography` package. Returns the .enc file path.
    """
    import json
    from datetime import datetime
    from pathlib import Path

    from guardian_ai.encryption import Encryption

    rows = conn.execute(
        "SELECT id, agent, request, result, timestamp FROM audit_logs "
        "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    payload = json.dumps(
        [{"id": r[0], "agent": r[1], "request": r[2],
          "result": r[3], "timestamp": r[4]} for r in rows],
        ensure_ascii=False, indent=2)
    blob = Encryption().encrypt(payload)

    directory = Path(out_dir) if out_dir else Path(DB_PATH).parent
    path = directory / f"audit_export_{datetime.now():%Y%m%d_%H%M%S}.enc"
    path.write_text(blob, encoding="utf-8")
    return str(path)


__all__ = ["init_database", "audit_log", "record_tasks", "export_audit",
           "verify_audit_chain", "DB_PATH"]
