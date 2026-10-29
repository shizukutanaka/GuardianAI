
"""Agent Connector: 複数 Agent を接続・並列実行"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from typing import List, Dict, Any
from guardian_ai.router import Router, AgentType

class AgentConnector:
    """複数の Agent を並列で実行・結果を統合"""
    
    def __init__(self, agents: List[dict]):
        """agents: [{'name': 'accounting', 'router': Router}, ...]"""
        self.agents = agents
    
    async def run_parallel(self, request: str) -> Dict[str, Dict]:
        """すべての Agent を並列で実行"""
        tasks = [
            lambda a, req: a['router'].analyze(req)(a)
            for a, req in zip(self.agents, [request] * len(self.agents))
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        output = {}
        for i, (agent, result) in enumerate(zip(self.agents, results)):
            if isinstance(result, Exception):
                output[agent['name']] = {"error": str(result)}
            else:
                output[agent['name']] = result
        
        return output
    
    def run_sequential(self, request: str) -> Dict[str, Dict]:
        """順次実行"""
        results = {}
        for agent in self.agents:
            results[agent['name']] = agent['router'].analyze(request)
        return results

# クラスをモジュールレベルに公開
__all__ = ["AgentConnector"]
