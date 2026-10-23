"""Skeptic agent: differential review of a proposed patch.

The Skeptic does not opine; it executes. A patch is accepted only if:
  1. Scope — the diff touches the suspect file and/or test files, nothing else.
  2. Differential — the failing evidence actually discriminates: the suite
     (or the patch's own test changes, applied alone) FAILS on the unpatched
     tree and PASSES on the patched tree. A patch whose "regression test"
     also passes without the fix proves nothing and is rejected.

This mirrors the MOLT-CORE differential-fuzzing discipline: claims are only
as good as the run that tried to break them.
"""

from __future__ import annotations

import os
import shutil
import tempfile

from .. import sandbox
from . import patcher_llm


def _is_test(path: str) -> bool:
    return patcher_llm._is_test_path(path)


def review(repo_dir: str, patch_info: dict, baseline, post,
           timeout: int = 120) -> dict:
    diff = patch_info.get("diff", "")
    files = [fp["path"] for fp in patcher_llm.parse_diff(diff)] if diff else []
    if not files and patch_info.get("file"):
        files = [patch_info["file"]]
    suspect = patch_info.get("file")
    violations = [f for f in files if f != suspect and not _is_test(f)]
    scope_ok = not violations

    differential = {"method": "baseline/post execution evidence",
                    "fail_before": None, "pass_after": None}
    if baseline is not None:
        differential["fail_before"] = not baseline.ok
    if post is not None:
        differential["pass_after"] = bool(post.ok)

    # Stronger differential when the patch carries its own test changes:
    # apply ONLY the test changes to a pristine copy — the suite must fail.
    _src_diff, test_diff = patcher_llm.split_diff(diff) if diff else ("", "")
    if test_diff.strip():
        tmp = sandbox.sandbox_tmpdir(prefix="molt_skeptic_")
        cand = os.path.join(tmp, "work")
        shutil.copytree(repo_dir, cand)
        try:
            patcher_llm.apply_diff(cand, test_diff)
            res = sandbox.run_in_dir(cand, sandbox.test_command(cand), timeout=timeout)
            differential = {"method": "test-only diff applied to unpatched tree",
                            "fail_before": not res.ok,
                            "pass_after": bool(post.ok) if post is not None else None,
                            "test_only_exit_code": res.returncode}
        except Exception as exc:
            differential = {"method": "test-only diff failed to apply",
                            "fail_before": None,
                            "pass_after": bool(post.ok) if post is not None else None,
                            "error": str(exc)}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    accept = bool(scope_ok
                  and differential.get("fail_before")
                  and differential.get("pass_after"))
    notes = []
    if not scope_ok:
        notes.append(f"diff touches out-of-scope files: {violations}")
    if differential.get("fail_before") is not True:
        notes.append("no evidence the failing tests fail on the unpatched tree")
    if differential.get("pass_after") is not True:
        notes.append("patched suite did not pass")
    if accept:
        notes.append("scope clean; differential holds (fails before, passes after)")
    return {"accept": accept, "scope_ok": scope_ok, "changed_files": files,
            "scope_violations": violations, "differential": differential,
            "notes": notes}
