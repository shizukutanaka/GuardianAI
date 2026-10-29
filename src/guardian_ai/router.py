"""Agent Router: ユーザー要求を解析し、適切な Agent を選択"""

from enum import Enum
from typing import Optional

class AgentType(Enum):
    """Agent タイプ分類"""
    ACCOUNTING = "accounting"
    LEGAL = "legal"
    HR = "hr"
    IT = "it"
    DEVELOPER = "developer"
    MEDICAL = "medical"
    GENERAL = "general"

class RouterConfig:
    def __init__(self):
        self.model_map = {"8b": ["llama3:8b"], "32b": ["llama3:70b"]}
        self.default_model = "qwen2:1.5b"
    
    def select_model(self, complexity):
        if complexity == "complex":
            return self.model_map["32b"][0]
        return self.model_map["8b"][0]

class Router:
    def __init__(self, config=None):
        self.config = config or RouterConfig()
    
    def analyze(self, request):
        agent = self.classify_agent(request)
        complexity = self.estimate_complexity(request)
        model = self.config.select_model(complexity)
        tasks = self.decompose_tasks(request, agent)
        
        # LLM inference (optional, for actual processing)
        # To enable: install llama-cpp-python and uncomment below
        # result = self.llm_inference(request, model)
        
        return {"agent": agent.value, "model": model, "complexity": complexity, "tasks": tasks}
    
    def classify_agent(self, request):
        if "決算" in request or "仕訳" in request:
            return AgentType.ACCOUNTING
        if "契約書" in request or "リスク" in request:
            return AgentType.LEGAL
        if "履歴書" in request:
            return AgentType.HR
        if "サーバー" in request or "ログ" in request:
            return AgentType.IT
        if "git" in request or "コード" in request:
            return AgentType.DEVELOPER
        if "カルテ" in request:
            return AgentType.MEDICAL
        return AgentType.GENERAL
    
    def estimate_complexity(self, request):
        return "complex" if "計画" in request.lower() else "medium"
    
    def decompose_tasks(self, request, agent):
        return [{"id": 1, "type": "ingestion", "desc": "読み込み"}]
