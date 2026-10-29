"""Main: Guardian AI プラットフォーム入口"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from guardian_ai.router import Router, AgentType
from guardian_ai.connector import AgentConnector

def load_config(path: str = "config/model_selector.json"):
    """Config を読み込む"""
    path_obj = Path(__file__).parent.parent / path
    with open(path_obj) as f:
        return json.load(f)

def main():
    config = load_config()
    print(f"Config loaded: {config.get('model_selector', {})}")
    
    # Agent を構築
    agents = [
        {"name": "accounting", "router": Router()},
        {"name": "legal", "router": Router()},
        {"name": "general", "router": Router()},
    ]
    
    connector = AgentConnector(agents)
    
    # テスト
    request = "決算書のリスク評価と概要要約"
    results = connector.run_parallel(request)
    print(f"Results: {results}")
    
    # LLM 実行（コメントアウト中）
    # print("\n=== LLM Inference (disabled) ===")
    # result = agents[0]["router"].llm_inference(request, "llama3:8b")
    # print(f"LLM result: {result}")

if __name__ == "__main__":
    main()