"""Agent Router: ユーザー要求を解析し、適切な Agent を選択"""

import json
from enum import Enum
from pathlib import Path

from guardian_ai.first_principles import FirstPrinciples

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "model_selector.json"


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
    """Model selection. Reads config/model_selector.json when present."""

    def __init__(self, config_path=None):
        self.default_model = "llama3:8b"
        self.complexity_map = {"simple": "llama3:8b",
                               "medium": "llama3:8b",
                               "complex": "llama3:70b"}
        path = Path(config_path) if config_path else _CONFIG_PATH
        try:
            data = json.loads(path.read_text(encoding="utf-8"))["model_selector"]
            self.default_model = data.get("default", self.default_model)
            self.complexity_map.update(data.get("complexity", {}))
        except (OSError, KeyError, ValueError):
            pass  # no config file or malformed -> defaults are the truth

    def select_model(self, complexity):
        return self.complexity_map.get(complexity, self.default_model)


class Router:
    def __init__(self, config=None):
        self.config = config or RouterConfig()
        self.thinker = FirstPrinciples()

    def analyze(self, request):
        agent = self.classify_agent(request)
        complexity = self.estimate_complexity(request)
        model = self.config.select_model(complexity)

        # First principles: strip assumptions -> fundamentals -> unknowns -> reconstruct
        thinking = self.thinker.think(request, agent, complexity)
        tasks = thinking["plan"]

        return {"agent": agent.value, "model": model, "complexity": complexity,
                "tasks": tasks, "thinking": thinking}

    def classify_agent(self, request):
        if "決算" in request or "仕訳" in request:
            return AgentType.ACCOUNTING
        if "契約書" in request or "法律" in request or "リスク" in request:
            return AgentType.LEGAL
        if "履歴書" in request:
            return AgentType.HR
        if "サーバー" in request or "ログ" in request or "障害" in request:
            return AgentType.IT
        if "git" in request or "コード" in request:
            return AgentType.DEVELOPER
        if "カルテ" in request:
            return AgentType.MEDICAL
        return AgentType.GENERAL

    def estimate_complexity(self, request):
        lowered = request.lower()
        if "計画" in request or "プラン" in request or "plan" in lowered:
            return "complex"
        return "medium"

    def decompose_tasks(self, request, agent):
        """First-principles task decomposition (strip -> fundamentals -> unknowns -> reconstruct)."""
        thinking = self.thinker.think(request, agent, self.estimate_complexity(request))
        return thinking["plan"]
