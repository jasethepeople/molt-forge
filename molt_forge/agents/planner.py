"""Planner agent: decomposes the investigation into ordered, logged steps."""

from __future__ import annotations

STEPS = [
    ("intake", "Clone repository and pin commit SHA"),
    ("inventory", "Inventory languages and detect test commands"),
    ("baseline", "Run test suite in sandbox to establish baseline"),
    ("analyze", "Analyze failures and locate suspect code"),
    ("patch", "Generate candidate patches + regression test"),
    ("verify", "Re-run tests on patched tree; decide verdict from exit codes"),
    ("package", "Build hash-manifested evidence package"),
]


def plan(repo_info: dict) -> list[dict]:
    steps = [{"step": name, "description": desc, "status": "pending"} for name, desc in STEPS]
    if not repo_info.get("has_tests"):
        # Without tests we can still diagnose, but never "validate".
        for s in steps:
            if s["step"] in ("patch", "verify"):
                s["description"] += " (limited: no test suite detected)"
    return steps
