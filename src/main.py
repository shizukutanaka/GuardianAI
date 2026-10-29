
"""Shield AI - Privacy-First Enterprise Agent Platform"""
# Zero Trust, Privacy by Design
# NO INTERNET ACCESS - Local-only operation
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from guardian_ai.router import Router, AgentType
from guardian_ai.connector import AgentConnector
from guardian_ai.local_search import LocalSearch

def main():
    router = Router()
    connector = AgentConnector([router])
    
    # Local Search
    search = LocalSearch(".")
    
    # 基本テスト
    for agent_name in ["accounting", "legal", "general"]:
        request = "決算書のリスク評価" if agent_name == "accounting" else "契約書の法律リスク" if agent_name == "legal" else "一般事務処理"
        result = router.analyze(request)
        print(f"  {agent_name}: {result['agent']}/{result['model']}")
        
    print("\nAll agents initialized successfully!")

if __name__ == "__main__":
    main()
