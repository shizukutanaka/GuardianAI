"""ShieldAI Database - SQLite schema and initialization"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "shield_ai.db")

def init_database():
    """Initialize database schema"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Create agents table
    c.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            model TEXT NOT NULL,
            complexity TEXT DEFAULT 'medium',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create audit_logs table
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
    
    # Create task_queue table
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
    
    conn.commit()
    # Keep connection open for audit logging
    # conn.close()  # Deliberately not closing for audit logging
    print(f"Database initialized: {DB_PATH}")
    return conn
