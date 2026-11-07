"""ShieldAI Database - SQLite schema and initialization"""
import hashlib
import hmac
import sqlite3
import threading

from guardian_ai.paths import data_dir

DB_PATH = str(data_dir() / "shield_ai.db")

_EXPECTED_TRIGGERS = (
    "audit_no_update", "audit_no_delete",
    "queue_no_update", "queue_no_delete",
    "tasks_no_update", "tasks_no_delete",
)

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
    # check_same_thread=False lets the web UI pool connections across
    # request threads; SQLite itself is serialised so this is safe, and
    # _chain_lock covers the audit append critical section.
    conn = sqlite3.connect(db_path, check_same_thread=False)
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
            description TEXT,
            audit_entry_id INTEGER,
            row_hmac TEXT,
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
            row_hmac TEXT,
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
    for trig in ("audit_no_update", "audit_no_delete",
                 "tasks_no_update", "tasks_no_delete",
                 "queue_no_update", "queue_no_delete"):
        conn.execute(f"DROP TRIGGER IF EXISTS {trig}")
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
    # task_queue/tasks are written by INSERT only (record_tasks never
    # UPDATEs), so the same append-only rule protects them from a
    # silent status rewrite - verified the task record is not decorable.
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS queue_no_update
        BEFORE UPDATE ON task_queue
        BEGIN SELECT RAISE(ABORT, 'task_queue is append-only'); END
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS queue_no_delete
        BEFORE DELETE ON task_queue
        BEGIN SELECT RAISE(ABORT, 'task_queue is append-only'); END
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS tasks_no_update
        BEFORE UPDATE ON tasks
        BEGIN SELECT RAISE(ABORT, 'tasks is append-only'); END
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS tasks_no_delete
        BEFORE DELETE ON tasks
        BEGIN SELECT RAISE(ABORT, 'tasks is append-only'); END
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
    task_cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
    if task_cols and "description" not in task_cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN description TEXT")
        conn.commit()
    if task_cols and "audit_entry_id" not in task_cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN audit_entry_id INTEGER")
        conn.commit()
    q_cols = {r[1] for r in conn.execute("PRAGMA table_info(task_queue)")}
    if q_cols and "row_hmac" not in q_cols:
        conn.execute("ALTER TABLE task_queue ADD COLUMN row_hmac TEXT")
        conn.commit()
    if task_cols and "row_hmac" not in task_cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN row_hmac TEXT")
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


def _row_hmac(*parts) -> str:
    """HMAC a work-record row so a forged INSERT is detectable - an
    attacker can add rows but cannot compute a valid signature without
    the KMS-protected key."""
    from guardian_ai.kms import get_key
    body = "|".join(str(p) for p in parts)
    return hmac.new(get_key("audit_chain"), body.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def _task_hmac(task_id: int, agent: str, status: str,
               priority: str) -> str:
    return _row_hmac(task_id, agent, status, priority)


def _state_hmac(row_count: int, head: str) -> str:
    """Keyed MAC over the authenticated chain head+count. Deleting the
    newest rows leaves a valid chain but a stale state -> detected."""
    from guardian_ai.kms import get_key
    return hmac.new(get_key("audit_chain"),
                    f"{row_count}|{head}".encode("utf-8"),
                    hashlib.sha256).hexdigest()


def _update_chain_state(conn: sqlite3.Connection,
                        commit: bool = True) -> None:
    row = conn.execute(
        "SELECT COUNT(*), (SELECT chain_hash FROM audit_logs "
        "ORDER BY id DESC LIMIT 1) FROM audit_logs").fetchone()
    conn.execute(
        "INSERT INTO chain_state (id, row_count, head, state_hmac) "
        "VALUES (1, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
        "row_count=excluded.row_count, head=excluded.head, "
        "state_hmac=excluded.state_hmac",
        (row[0], row[1] or "", _state_hmac(row[0], row[1] or "")))
    if commit:
        conn.commit()


def _resync_chain_state(conn: sqlite3.Connection) -> None:
    """Create or repair chain_state from intact rows (init-time)."""
    _update_chain_state(conn)


_chain_lock = threading.Lock()


def audit_log(conn: sqlite3.Connection, agent: str, request: str,
              result: str, latency_ms: int = None) -> int:
    """Append one entry to audit_logs, commit, and return its row id.

    The read-head -> hash -> insert -> update_state sequence is a single
    critical section: two concurrent writers (e.g. ThreadingHTTPServer
    request threads, each with its own connection) would otherwise chain
    off the same prev head and fork the chain - which verify then reports
    as 'broken' even though nobody tampered. The lock serialises the
    append in-process (the DB is one file, so that is the correct scope)."""
    with _chain_lock:
        prev_row = conn.execute(
            "SELECT chain_hash FROM audit_logs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        prev = prev_row[0] if prev_row and prev_row[0] else ""
        ts = conn.execute("SELECT CURRENT_TIMESTAMP").fetchone()[0]
        h = _chain_hash(prev, agent, request, result, ts)
        cur = conn.execute(
            "INSERT INTO audit_logs (agent, request, result, timestamp, "
            "latency_ms, chain_hash) VALUES (?, ?, ?, ?, ?, ?)",
            (agent, request, result, ts, latency_ms, h))
        # one transaction: the row insert + chain_state update commit
        # together, so a crash can never leave a committed row beside a
        # stale state (which would read as 'tail deleted' - a false
        # tamper report).
        _update_chain_state(conn, commit=False)
        conn.commit()
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
    # Missing chain_state with rows present IS tampering - init always
    # creates it, so its absence means the attacker deleted it to evade
    # the tail-deletion check below.
    if not state and rows:
        return {"ok": False, "broken_at": None,
                "reason": "chain_state missing - possible tamper"}
    if state:
        scount, shead, shmac = state
        if shmac != _state_hmac(scount, shead):
            return {"ok": False, "broken_at": None,
                    "reason": "chain_state signature invalid"}
        if scount != len(rows) or shead != (prev or ""):
            return {"ok": False, "broken_at": None,
                    "reason": "tail rows deleted or head replaced"}
    # The append-only layer is enforcement, not content - verify it is
    # actually present (an attacker could DROP the triggers while the
    # chain stays intact, so reporting its presence is honest).
    present = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()}
    missing = [t for t in _EXPECTED_TRIGGERS if t not in present]
    # Forged task_queue rows: each row is HMAC-signed with the audit key
    # at insert time. Verify the SIGNATURE, not just its presence - a
    # fabricated row with any string in row_hmac must fail recomputation.
    # Legacy rows (pre-signing, NULL) are honest, not forged.
    bad = 0
    for tid, agent, st, pri, sig in conn.execute(
            "SELECT task_id, agent, status, priority, row_hmac "
            "FROM task_queue WHERE row_hmac IS NOT NULL").fetchall():
        if sig != _task_hmac(tid, agent, st, pri):
            bad += 1
    # an unsigned row newer than the last signed one = forged insert;
    # if NO signed rows exist yet, all NULL rows are legacy (honest) -
    # use max-int as the threshold so nothing is falsely flagged.
    unsigned = conn.execute(
        "SELECT COUNT(*) FROM task_queue WHERE row_hmac IS NULL "
        "AND id > COALESCE((SELECT MAX(id) FROM task_queue "
        "WHERE row_hmac IS NOT NULL), 9223372036854775807)"
    ).fetchone()[0]
    bad += unsigned
    # tasks rows are signed too - a forged description/audit_entry_id
    # must fail recomputation (both tables of the work record are covered).
    for ag, pri, desc, eid, sig in conn.execute(
            "SELECT agent, priority, description, audit_entry_id, "
            "row_hmac FROM tasks WHERE row_hmac IS NOT NULL").fetchall():
        if sig != _row_hmac(ag, pri, desc, eid):
            bad += 1
    tunsigned = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE row_hmac IS NULL "
        "AND id > COALESCE((SELECT MAX(id) FROM tasks "
        "WHERE row_hmac IS NOT NULL), 9223372036854775807)"
    ).fetchone()[0]
    bad += tunsigned
    return {"ok": bad == 0, "broken_at": None, "entries": len(rows),
            "triggers_missing": missing, "forged_tasks": bad,
            "reason": f"{bad} forged work-record row(s) - invalid "
                      "signature" if bad else None}


def record_tasks(conn: sqlite3.Connection, agent: str, complexity: str,
                 steps: list, execution_steps: list = None,
                 audit_entry_id: int = None) -> None:
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
            status = "pending"  # no execution info - do not claim 'done'
        else:
            status = status_by_type.get(stype, "skipped")
            # 'skipped' is honest when a gate (e.g. PHI) stopped the run
        desc = step.get("description") or step.get("text") or stype
        cur = conn.execute(
            "INSERT INTO tasks (agent, priority, description, "
            "audit_entry_id, row_hmac) VALUES (?, ?, ?, ?, ?)",
            (agent, priority, desc, audit_entry_id,
             _row_hmac(agent, priority, desc, audit_entry_id)))
        tid = cur.lastrowid
        conn.execute(
            "INSERT INTO task_queue (task_id, agent, status, priority, "
            "row_hmac) VALUES (?, ?, ?, ?, ?)",
            (tid, agent, status, priority,
             _task_hmac(tid, agent, status, priority)))
    conn.commit()


def export_audit(conn: sqlite3.Connection, limit: int = None,
                 out_dir: str = None) -> str:
    """Export audit entries as an AES-256-GCM file. Exports ALL entries by
    default - a partial export is not a complete audit trail. `truncated`
    flags an intentional cap (limit set).

    Requires the `cryptography` package. Returns the .enc file path.
    """
    import json
    from datetime import datetime
    from pathlib import Path

    from guardian_ai.encryption import Encryption

    if limit is None:
        rows = conn.execute(
            "SELECT id, agent, request, result, timestamp, chain_hash "
            "FROM audit_logs ORDER BY id DESC").fetchall()
    else:
        rows = conn.execute(
            "SELECT id, agent, request, result, timestamp, chain_hash "
            "FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]
    truncated = len(rows) < total
    state = conn.execute(
        "SELECT row_count, head, state_hmac FROM chain_state "
        "WHERE id = 1").fetchone()
    # A complete audit snapshot includes the work record, not just the
    # event log - tasks/task_queue show what was planned and its outcome.
    tasks = conn.execute(
        "SELECT t.id, t.agent, t.priority, t.description, "
        "t.audit_entry_id, q.status FROM tasks t "
        "LEFT JOIN task_queue q ON q.task_id = t.id").fetchall()
    # Anchor: embedding the signed chain head lets a stored export prove
    # the DB state at export time - an attacker who later rolls back
    # audit rows + chain_state cannot alter this file (AES-GCM, key kept
    # outside the DB), so the rollback becomes detectable.
    payload = json.dumps(
        {"chain_state": {"row_count": state[0], "head": state[1],
                         "state_hmac": state[2]} if state else None,
         "truncated": truncated,
         "entries": [{"id": r[0], "agent": r[1], "request": r[2],
                      "result": r[3], "timestamp": r[4],
                      "chain_hash": r[5]} for r in rows],
         # work_record is operational state, not audit-grade - it is not
         # chain-protected and can be falsified by INSERT (task_queue is
         # the working queue, audit_logs is the immutable record). Mark
         # it so the snapshot is not mistaken for verified audit data.
         "work_record_unverified": True,
         "work_record": [{"id": t[0], "agent": t[1], "priority": t[2],
                          "description": t[3], "audit_entry_id": t[4],
                          "status": t[5]} for t in tasks]},
        ensure_ascii=False, indent=2)
    blob = Encryption().encrypt(payload)

    directory = Path(out_dir) if out_dir else Path(DB_PATH).parent
    path = directory / f"audit_export_{datetime.now():%Y%m%d_%H%M%S}.enc"
    path.write_text(blob, encoding="utf-8")
    return str(path)


__all__ = ["init_database", "audit_log", "record_tasks", "export_audit",
           "verify_audit_chain", "DB_PATH"]
