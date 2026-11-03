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
    
    # Create tasks table (referenced by task_queue)
    c.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent TEXT NOT NULL,
            priority TEXT DEFAULT 'medium',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
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

def main():
    from guardian_ai.router import Router, AgentType
    from guardian_ai.connector import AgentConnector
    from guardian_ai.local_search import LocalSearch
    from guardian_ai.db import init_database
    	
    router = Router()
    connector = AgentConnector([router])
    
    # Local Search
    search = LocalSearch(os.path.abspath("src"))
    
    # Initialize database once
    conn = init_database()
    
    # 基本テスト
    for agent_name in ["accounting", "legal", "general"]:
        request = "決算書のリスク評価" if agent_name == "accounting" else "契約書の法律リスク" if agent_name == "legal" else "一般事務処理"
        result = router.analyze(request)
        print(f"  {agent_name}: {result['agent']}/{result['model']}")
        # Audit log
        conn.execute("INSERT INTO audit_logs (agent, request, result) VALUES (?, ?, ?)",\
                     (agent_name, request, str(result)))
        conn.commit()
    	
    print("\nAll agents initialized successfully!")
    
    # CLI Input Loop - Elon First Principles: Maximum Value with Minimum Friction
    print("\n" + "=" * 50)
    print("SHIELDAI ENTERPRISE AGENT PLATFORM")
    print("=" * 50)
    print("Enter your request or 'quit' to exit:")
    print("  - 決算書のリスク評価 (accounting)")
    print("  - 契約書の法律リスク (legal)")
    print("  - サーバー障害分析 (it)")
    print("  - コードレビュー (developer)")
    print("  - 一般事務処理 (general)")
    print("  - モデル設定: 複数を選択 (model: multiple)")
    print("=" * 50 + "\n")

    while True:
        # Model preference mode
        mode = input("Model: ").strip().lower()
        if mode in ['quit', 'exit', 'q']:
            print("\nGoodbye!")
            break
        
        if mode == 'multiple':
            # Model preference mode
            continue
        # Developer mode: test command
        user_input = input("shieldai@> ").strip()
        if user_input.lower() in ['quit', 'exit', 'q']:
            print("\nGoodbye!")
            break
        
        if not user_input:
            continue
        
        # Parse request
        router = Router()
        result = router.analyze(user_input)
        
        print(f"\n📋 Agent: {result['agent']}")
        print(f"🧠 Model: {result['model']}")
        print(f"⚙️  Complexity: {result['complexity']}")
        print(f"📝 Tasks: {len(result['tasks'])}")
        
        # Audit logging - use a fresh connection
        conn = init_database()
        conn.execute("INSERT INTO audit_logs (agent, request, result) VALUES (?, ?, ?)", \
                     (result['agent'], user_input, str(result)))
        conn.commit()
        conn.close()
        
        print(f"\n✓ Request processed successfully\n")
        
        try:
            next_input = input("shieldai@> ").strip()
            if next_input.lower() in ['quit', 'exit', 'q']:
                print("\nGoodbye!")
                break
            if next_input:
                user_input = next_input
        except (KeyboardInterrupt, EOFError):
            break
        except ValueError:
            pass
if __name__ == "__main__":
    main()