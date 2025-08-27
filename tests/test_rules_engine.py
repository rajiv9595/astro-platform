
import pytest
from backend import rules_engine

def test_sign_lord_mapping():
    assert rules_engine.SIGN_LORD[1] == "Mars"
    assert rules_engine.SIGN_LORD[6] == "Mercury"
    assert rules_engine.SIGN_LORD[7] == "Venus"
    assert rules_engine.SIGN_LORD[11] == "Saturn"

def test_reload_rules_no_crash():
    res = rules_engine.reload_rules()
    assert isinstance(res, dict)
    assert "count" in res and "ids" in res and "errors" in res
