"""Unit tests for Agent Router"""
import sys
sys.path.insert(0, "..")
from guardian_ai.router import Router, RouterConfig, AgentType

def test_router_init():
    r = Router()
    assert r is not None

def test_classify_accounting():
    r = Router()
    result = r.classify_agent("決算書の解析")
    assert result == AgentType.ACCOUNTING

def test_classify_legal():
    r = Router()
    result = r.classify_agent("契約書のリスク評価")
    assert result == AgentType.LEGAL

def test_estimate_complexity():
    r = Router()
    assert r.estimate_complexity("計画書作成") == "complex"
    assert r.estimate_complexity("データ検索") == "medium"

if __name__ == "__main__":
    test_router_init()
    test_classify_accounting()
    test_classify_legal()
    test_estimate_complexity()
    print("All tests passed!")
