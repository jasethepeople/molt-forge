"""Intake: clone a public repo (URL or local path), pin its commit SHA,
inventory languages and detect plausible build/test commands."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

LANG_BY_EXT = {
    ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".java": "Java",
    ".go": "Go", ".rs": "Rust", ".c": "C", ".h": "C/C++ header", ".cpp": "C++",
    ".rb": "Ruby", ".sh": "Shell", ".html": "HTML", ".css": "CSS",
    ".md": "Markdown", ".json": "JSON", ".yml": "YAML", ".yaml": "YAML",
}

IGNORE_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv"}


def _git(args, cwd=None) -> str:
    out = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout.strip()


def clone_repo(repo_url: str, dest: str) -> str:
    """Clone (local paths and file:// URLs work offline). Returns pinned SHA."""
    _git(["clone", "--quiet", repo_url, dest])
    return _git(["rev-parse", "HEAD"], cwd=dest)


def inventory(repo_dir: str) -> dict:
    files = []
    lang_counts: dict[str, int] = {}
    for root, dirs, names in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for name in names:
            full = os.path.join(root, name)
            rel = os.path.relpath(full, repo_dir)
            files.append(rel)
            lang = LANG_BY_EXT.get(Path(name).suffix.lower(), "other")
            lang_counts[lang] = lang_counts.get(lang, 0) + 1
    files.sort()
    from . import stacks
    spec = stacks.detect_stack(repo_dir)
    py_tests = any("test" in f.lower() and f.endswith(".py") for f in files)
    # Stack-aware: a Rust repo has tests because Cargo.toml says so, not
    # because a .py test file exists (the old check made Rust repos invisible).
    has_tests = py_tests if spec is None or spec["stack"] == "python" else True
    build = []
    if (Path(repo_dir) / "Makefile").exists():
        build.append("make test")
    if spec is not None:
        build.append(" ".join(spec["test_command"]))
    return {"files": files, "languages": lang_counts, "stack": spec["stack"] if spec else None,
            "has_tests": has_tests, "candidate_test_commands": build}


def intake(repo_url: str, workdir: str) -> dict:
    dest = os.path.join(workdir, "repo")
    sha = clone_repo(repo_url, dest)
    inv = inventory(dest)
    return {"repo_url": repo_url, "pinned_sha": sha, "repo_dir": dest, **inv}
