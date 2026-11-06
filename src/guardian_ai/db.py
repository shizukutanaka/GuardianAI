"""ShieldAI Database - SQLite schema and initialization"""
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
            FOREIGN KEY (agent) REFERENCES agents (name)
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

    conn.commit()
    return conn


def audit_log(conn: sqlite3.Connection, agent: str, request: str, result: str) -> int:
    """Append one entry to audit_logs, commit, and return its row id."""
    cur = conn.execute(
        "INSERT INTO audit_logs (agent, request, result) VALUES (?, ?, ?)",
        (agent, request, result))
    conn.commit()
    return cur.lastrowid


def record_tasks(conn: sqlite3.Connection, agent: str, complexity: str,
                 steps: list) -> None:
    """Persist a plan's steps into tasks + task_queue (status=done)."""
    priority = "high" if complexity == "complex" else "medium"
    for step in steps:
        cur = conn.execute(
            "INSERT INTO tasks (agent, priority) VALUES (?, ?)", (agent, priority))
        conn.execute(
            "INSERT INTO task_queue (task_id, agent, status, priority) "
            "VALUES (?, ?, 'done', ?)", (cur.lastrowid, agent, priority))
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


__all__ = ["init_database", "audit_log", "record_tasks", "export_audit", "DB_PATH"]
