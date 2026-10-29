"""Agent Connector: 複数 Agent を接続・並列実行"""

import asyncio
from typing import List, Dict
from guardian_ai.router import Router, AgentType

class AgentConnector:
    """複数の Agent を並列で実行・結果を統合"""
    
    def __init__(self, agents: List[dict]):
        """agents: [{'name': 'accounting', 'router': Router}, ...]"""
        self.agents = agents
    
    def run_parallel(self, request: str) -> Dict[str, Dict]:
        """すべての Agent を並列で実行"""
        results = {}
        for agent in self.agents:
            result = agent["router"].analyze(request)
            results[agent["name"]] = result
        
        return results

# 例：複数 Agent を定義
agents_config = [
    {"name": "accounting", "router": Router()},
    {"name": "legal", "router": Router()},
    {"name": "general", "router": Router()},
]