"""Regression checks for the redacted Chord audit response parser."""

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "chord_audit.py"
SPEC = importlib.util.spec_from_file_location("chord_audit", SCRIPT)
audit = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(audit)


def test_tool_names_accepts_current_top_level_array():
    payload = [
        {"name": "link_identity", "input_schema": {"type": "object"}},
        {"name": "get_catalog", "input_schema": {"type": "object"}},
    ]
    assert audit.tool_names(payload) == {"link_identity", "get_catalog"}


def test_tool_names_keeps_legacy_wrapped_shape():
    payload = {"data": {"tools": [{"name": "get_catalog"}]}}
    assert audit.tool_names(payload) == {"get_catalog"}
