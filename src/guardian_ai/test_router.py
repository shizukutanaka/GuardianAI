"""Unit tests"""
import sys
sys.path.insert(0, "..")
from guardian_ai.router import Router, AgentType

r = Router()
assert r.classify_agent("決算") == AgentType.ACCOUNTING
assert r.classify_agent("契約書") == AgentType.LEGAL
assert r.estimate_complexity("計画") == "complex"
print("All tests passed!")

