"""Patcher agent: generates real unified-diff patches + a regression test.

Strategy (deterministic, honest): mutate the suspect source file one rule at a
time, run the full test suite in the sandbox for every candidate, and keep the
first mutation that makes the suite pass. A patch is only emitted together with
the execution evidence that selected it.
"""

from __future__ import annotations

import difflib
import os
import shutil
import tempfile

from .. import sandbox

MAX_CANDIDATES = 25


def make_unified_diff(rel_path: str, original: str, patched: str) -> str:
    return "".join(difflib.unified_diff(
        original.splitlines(keepends=True), patched.splitlines(keepends=True),
        fromfile=f"a/{rel_path}", tofile=f"b/{rel_path}"))


def build_regression_test(failing_test_source: str, source_name: str) -> str:
    header = ('"""Regression test captured by MOLT Forge.\n'
              f'Copied from the repository test "{source_name}" that exposed the bug.\n'
              'It failed before the patch and must pass after it.\n"""\n')
    return header + failing_test_source


def generate_patch(repo_dir: str, suspect_file: str, failing_test_file: str | None,
                   backend, timeout: int = 120, log=lambda *_: None) -> dict:
    """Try candidate mutations; return patch info or an honest failure record."""
    src_path = os.path.join(repo_dir, suspect_file)
    with open(src_path, "r", encoding="utf-8") as fh:
        original = fh.read()

    candidates = backend.mutations(original)[:MAX_CANDIDATES]
    log(f"{len(candidates)} candidate mutations for {suspect_file}")
    attempts = []
    for i, (desc, mutated) in enumerate(candidates):
        tmp = sandbox.sandbox_tmpdir(prefix="molt_candidate_")
        cand_dir = os.path.join(tmp, "work")
        shutil.copytree(repo_dir, cand_dir)
        with open(os.path.join(cand_dir, suspect_file), "w", encoding="utf-8") as fh:
            fh.write(mutated)
        result = sandbox.run_in_dir(cand_dir, sandbox.test_command(cand_dir), timeout=timeout)
        attempts.append({"candidate": i, "mutation": desc,
                         "exit_code": result.returncode, "timed_out": result.timed_out})
        log(f"candidate {i}: {desc} -> exit {result.returncode}")
        if result.ok:
            shutil.rmtree(tmp, ignore_errors=True)
            regression = ""
            if failing_test_file:
                with open(os.path.join(repo_dir, failing_test_file), encoding="utf-8") as fh:
                    regression = build_regression_test(fh.read(), failing_test_file)
            return {
                "patched": True,
                "file": suspect_file,
                "mutation": desc,
                "diff": make_unified_diff(suspect_file, original, mutated),
                "patched_source": mutated,
                "regression_test": regression,
                "regression_test_name": "regression_test.py",
                "attempts": attempts,
            }
        shutil.rmtree(tmp, ignore_errors=True)
    return {"patched": False, "file": suspect_file, "attempts": attempts,
            "reason": "no candidate mutation made the test suite pass"}
