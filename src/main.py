
"""ShieldAI Database - SQLite schema and initialization"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "shield_ai.db")

def init_database():
    """Initialize database schema"""
    conn = sqlite3.connect(DB_PATH)
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
    conn.close()
    print(f"Database initialized: {DB_PATH}")

def main():
    from guardian_ai.router import Router, AgentType
    from guardian_ai.connector import AgentConnector
    from guardian_ai.local_search import LocalSearch
    from guardian_ai.db import init_database
    
    router = Router()
    connector = AgentConnector([router])
    
    # Local Search
    search = LocalSearch(os.path.abspath("src"))
    
    # Initialize database and get connection for audit logging
    conn = init_database()
    
    # 基本テスト
    for agent_name in ["accounting", "legal", "general"]:
        request = "決算書のリスク評価" if agent_name == "accounting" else "契約書の法律リスク" if agent_name == "legal" else "一般事務処理"
        result = router.analyze(request)
        print(f"  {agent_name}: {result['agent']}/{result['model']}")
        # Audit log
        conn.execute("INSERT INTO audit_logs (agent, request, result) VALUES (?, ?, ?)",
                     (agent_name, request, str(result)))
        conn.commit()
    
    print("\nAll agents initialized successfully!")


if __name__ == "__main__":
    main()
