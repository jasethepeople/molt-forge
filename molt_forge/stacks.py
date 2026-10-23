"""Stack detection: map a repository's manifest to its test command.

This is the table that frees Forge from being Python-only. Detection is by
manifest file, in a fixed priority order; the returned spec also carries the
resource envelope a cold build of that stack realistically needs.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PYTHON_FALLBACK_TIMEOUT = 120


def _python_command(repo_dir: str) -> list:
    import importlib.util
    if importlib.util.find_spec("pytest") is not None:
        return [sys.executable, "-m", "pytest", "-q", "--tb=long", "-rf"]
    return [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"]


def detect_stack(repo_dir: str) -> dict | None:
    """Return {stack, manifest, test_command, timeout, cpu_seconds, mem_mb} or None."""
    root = Path(repo_dir)
    if (root / "Cargo.toml").exists():
        return {"stack": "rust", "manifest": "Cargo.toml",
                "test_command": ["cargo", "test"],
                "timeout": 900, "cpu_seconds": 600, "mem_mb": 4096}
    pkg_json = root / "package.json"
    if pkg_json.exists():
        try:
            scripts = json.loads(pkg_json.read_text(encoding="utf-8")).get("scripts", {})
        except Exception:
            scripts = {}
        test_script = scripts.get("test", "")
        if test_script and "no test specified" not in test_script:
            return {"stack": "node", "manifest": "package.json",
                    "test_command": ["npm", "test", "--silent"],
                    "timeout": 600, "cpu_seconds": 300, "mem_mb": 2048}
        return None
    has_python = any((root / m).exists() for m in
                     ("pyproject.toml", "setup.py", "requirements.txt", "pytest.ini"))
    if not has_python:
        has_python = any(str(p).endswith(".py") for p in root.rglob("*.py")
                         if ".git" not in p.parts)
    if has_python:
        return {"stack": "python", "manifest": "pyproject.toml/setup.py/*.py",
                "test_command": _python_command(repo_dir),
                "timeout": PYTHON_FALLBACK_TIMEOUT, "cpu_seconds": 60, "mem_mb": 1024}
    return None


def test_command(repo_dir: str) -> list:
    spec = detect_stack(repo_dir)
    if spec is not None:
        return list(spec["test_command"])
    return _python_command(repo_dir)


def run_envelope(repo_dir: str) -> dict:
    """Timeouts/limits for running this repo's suite in the sandbox."""
    spec = detect_stack(repo_dir)
    if spec is None:
        return {"timeout": PYTHON_FALLBACK_TIMEOUT, "cpu_seconds": 60, "mem_mb": 1024}
    return {"timeout": spec["timeout"], "cpu_seconds": spec["cpu_seconds"],
            "mem_mb": spec["mem_mb"]}
