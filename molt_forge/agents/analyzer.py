"""Analyzer agent: turns raw sandboxed test output into structured findings."""

from __future__ import annotations

import os

def _relativize(path: str | None, repo_files: list[str]) -> str | None:
    """Map an absolute traceback path (inside a sandbox temp copy) to a repo-relative path."""
    if not path:
        return None
    norm = path.replace("\\", "/")
    for rel in repo_files:
        if norm.endswith("/" + rel) or norm == rel:
            return rel
    return os.path.basename(path)


def analyze(backend, test_output: str, repo_files: list[str]) -> dict:
    findings = backend.analyze(test_output)
    findings["suspect_file"] = _relativize(findings.get("suspect_file"), repo_files)
    findings["failing_test_file"] = _relativize(findings.get("failing_test_file"), repo_files)
    # Guard: a "suspect" that is not actually in the repo inventory is a
    # parser artifact (the classic case: pytest reporting `<frozen runpy>` as
    # a frame when the host lacks a runner). Never let it reach the patcher.
    if findings.get("suspect_file") and findings["suspect_file"] not in repo_files:
        findings["suspect_rejected"] = findings["suspect_file"]
        findings["suspect_file"] = None
    if findings.get("failing_test_file") and findings["failing_test_file"] not in repo_files:
        findings["failing_test_file"] = None
    if not findings.get("suspect_file"):
        findings["suspect_file"] = _guess_source(findings.get("failing_test_file"), repo_files)
    findings["backend"] = getattr(backend, "name", "unknown")
    return findings


def _guess_source(failing_test_file: str | None, repo_files: list[str]) -> str | None:
    """Heuristic: tests/test_calc.py most likely exercises calc.py.

    Rust sibling: tests/genesis_protocol_regression.rs most likely exercises
    kernel/genesis.rs — the full test stem is tried first, then progressively
    shorter underscore prefixes (genesis_protocol_regression ->
    genesis_protocol -> genesis).
    """
    if not failing_test_file:
        return None
    base = os.path.basename(failing_test_file)
    ext = ""
    for e in (".py", ".rs"):
        if base.endswith(e):
            ext, base = e, base[: -len(e)]
            break
    if base.startswith("test_"):
        base = base[len("test_"):]
    stems = [base]
    if ext == ".rs":
        parts = base.split("_")
        for i in range(len(parts) - 1, 0, -1):
            stems.append("_".join(parts[:i]))
    for stem in stems:
        for rel in repo_files:
            if os.path.basename(rel) == stem + ext and "test" not in rel.lower():
                return rel
    return None
