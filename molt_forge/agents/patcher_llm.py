"""Model-authored patching: the Fixer asks the LLM for a unified diff.

Used for real repositories (any stack). The model proposes; only sandboxed
execution disposes — a diff is accepted solely when the repo's own test
suite passes with it applied, after bounded retries with the failure fed
back. The deterministic mutation patcher (patcher.py) remains the offline
fast path for the Python fixture.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile

from .. import sandbox
from .patcher import build_regression_test

MAX_ATTEMPTS = 3

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def extract_diff(text: str) -> str | None:
    """Pull a unified diff out of a model response (fences tolerated)."""
    if not text:
        return None
    fence = re.search(r"```(?:diff)?\n(.*?)```", text, re.S)
    if fence and ("--- " in fence.group(1) or "diff --git" in fence.group(1)):
        text = fence.group(1)
    start = None
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.startswith("diff --git ") or line.startswith("--- a/") or line.startswith("--- "):
            start = i
            break
    if start is None:
        return None
    return "".join(lines[start:]).strip() + "\n"


def parse_diff(diff: str) -> list[dict]:
    """Parse a unified diff into [{path, hunks: [(old_start, [lines])]}].

    Hunk bodies are consumed by the line counts in their @@ header — not by
    prefix guessing — so a following file's `--- ` header can never be
    swallowed into the previous hunk (the classic multi-file parse bug)."""
    files: list[dict] = []
    current = None
    hunk = None  # [old_start, lines, old_left, new_left]
    for line in diff.splitlines():
        if hunk is not None and (hunk[2] > 0 or hunk[3] > 0) and line[:1] in (" ", "-", "+"):
            hunk[1].append(line)
            if line[:1] in (" ", "-"):
                hunk[2] -= 1
            if line[:1] in (" ", "+"):
                hunk[3] -= 1
            continue
        hunk = None
        if line.startswith("diff --git "):
            current = None
        elif line.startswith("+++ b/"):
            current = {"path": line[6:].strip(), "hunks": []}
            files.append(current)
        elif line.startswith("+++ "):
            current = {"path": line[4:].strip().lstrip("/"), "hunks": []}
            files.append(current)
        elif HUNK_RE.match(line) and current is not None:
            m = HUNK_RE.match(line)
            hunk = [int(m.group(1)), [],
                    int(m.group(2) or 1), int(m.group(4) or 1)]
            current["hunks"].append((hunk[0], hunk[1]))
    return [f for f in files if f["hunks"]]


def split_diff(diff: str) -> tuple[str, str]:
    """Split a diff into (source-only diff, test-only diff) by file path."""
    if "diff --git " in diff:
        parts = re.split(r"(?m)(?=^diff --git )", diff)
        blocks = [p for p in parts if p.strip()]
    elif "\n--- " in diff or diff.startswith("--- "):
        parts = re.split(r"(?m)(?=^--- )", diff)
        blocks = [p for p in parts if p.strip()]
    else:
        blocks = [diff]
    src_parts, test_parts = [], []
    for block in blocks:
        m = re.search(r"^\+\+\+ b/(.+)$", block, re.M)
        path = m.group(1).strip() if m else ""
        (test_parts if _is_test_path(path) else src_parts).append(block)
    return "".join(src_parts), "".join(test_parts)


def _is_test_path(path: str) -> bool:
    base = os.path.basename(path)
    return ("test" in base.lower() or "/tests/" in path.replace("\\", "/")
            or path.replace("\\", "/").startswith("tests/"))


def apply_diff_to_text(text: str, file_patch: dict) -> str:
    """Apply one file's hunks to its content (exact context, small drift window)."""
    lines = text.splitlines(keepends=True)
    offset = 0
    for old_start, hunk_lines in file_patch["hunks"]:
        old_block = [l[1:] if l[1:].endswith("\n") else l[1:] + "\n"
                     for l in hunk_lines if l[:1] in (" ", "-")]
        pos = old_start - 1 + offset
        found = None
        for cand in range(max(0, pos - 5), min(len(lines) - len(old_block) + 1, pos + 6)):
            if lines[cand:cand + len(old_block)] == old_block:
                found = cand
                break
        if found is None:
            raise ValueError(f"hunk at line {old_start} does not apply to {file_patch['path']}")
        new_block = []
        for l in hunk_lines:
            if l[:1] in (" ", "+"):
                content = l[1:]
                new_block.append(content if content.endswith("\n") else content + "\n")
        lines[found:found + len(old_block)] = new_block
        offset += len(new_block) - len(old_block)
    return "".join(lines)


def apply_diff(repo_dir: str, diff: str) -> dict:
    """Apply a unified diff inside repo_dir; return {rel_path: new_source}."""
    changed = {}
    for fp in parse_diff(diff):
        full = os.path.join(repo_dir, fp["path"])
        original = ""
        if os.path.exists(full):
            with open(full, encoding="utf-8") as fh:
                original = fh.read()
        new = apply_diff_to_text(original, fp)
        os.makedirs(os.path.dirname(full) or repo_dir, exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(new)
        changed[fp["path"]] = new
    return changed


PROMPT_TEMPLATE = """You are the Fixer agent in MOLT Forge. A repository's test suite fails.
Produce ONE unified diff (git style, paths as a/<path> and b/<path>) that fixes the bug.
Rules: change as little as possible; do not edit tests unless a test itself is the bug;
output ONLY the diff, no explanation.

Failing test output (tail):
{failure}

Suspect file {suspect}:
```
{source}
```
{feedback}"""


def generate_patch_with_model(repo_dir: str, suspect_file: str, failing_output: str,
                              backend, failing_test_file: str | None = None,
                              timeout: int = 120, log=lambda *_: None,
                              max_attempts: int = MAX_ATTEMPTS) -> dict:
    """Ask the model for a diff; accept only a suite-passing candidate."""
    with open(os.path.join(repo_dir, suspect_file), encoding="utf-8") as fh:
        source = fh.read()
    attempts = []
    feedback = ""
    for i in range(max_attempts):
        prompt = PROMPT_TEMPLATE.format(
            failure=failing_output[-4000:], suspect=suspect_file,
            source=source[:12000], feedback=feedback)
        try:
            response = backend.generate(prompt)
        except Exception as exc:
            attempts.append({"candidate": i, "error": f"model call failed: {exc}"})
            return {"patched": False, "file": suspect_file, "attempts": attempts,
                    "reason": "model backend unavailable", "strategy": "llm-diff"}
        diff = extract_diff(response)
        if not diff:
            attempts.append({"candidate": i, "error": "no unified diff in model response"})
            feedback = "\nYour previous reply contained no unified diff. Output ONLY a diff.\n"
            continue
        tmp = sandbox.sandbox_tmpdir(prefix="molt_llm_candidate_")
        cand_dir = os.path.join(tmp, "work")
        shutil.copytree(repo_dir, cand_dir)
        try:
            changed = apply_diff(cand_dir, diff)
        except Exception as exc:
            attempts.append({"candidate": i, "error": f"diff does not apply: {exc}"})
            feedback = f"\nYour previous diff did not apply: {exc}. Produce a corrected diff.\n"
            shutil.rmtree(tmp, ignore_errors=True)
            continue
        result = sandbox.run_in_dir(cand_dir, sandbox.test_command(cand_dir), timeout=timeout)
        attempts.append({"candidate": i, "files": sorted(changed),
                         "exit_code": result.returncode, "timed_out": result.timed_out})
        log(f"llm candidate {i}: {sorted(changed)} -> exit {result.returncode}")
        if result.ok:
            regression, regression_name = "", "regression_test.py"
            _src, test_diff = split_diff(diff)
            test_files = [p for p in parse_diff(test_diff)]
            if test_files:
                tf = test_files[0]["path"]
                regression = changed.get(tf, "")
                regression_name = tf.replace("/", "__")
            elif failing_test_file and failing_test_file.endswith(".py"):
                with open(os.path.join(repo_dir, failing_test_file), encoding="utf-8") as fh:
                    regression = build_regression_test(fh.read(), failing_test_file)
            shutil.rmtree(tmp, ignore_errors=True)
            primary = suspect_file if suspect_file in changed else sorted(changed)[0]
            return {"patched": True, "file": primary, "mutation": "llm-diff",
                    "strategy": "llm-diff", "diff": diff,
                    "patched_source": changed[primary], "patched_files": changed,
                    "regression_test": regression, "regression_test_name": regression_name,
                    "attempts": attempts}
        feedback = ("\nYour previous diff was applied but the suite still failed:\n"
                    + (result.stdout + result.stderr)[-2000:] + "\nProduce a corrected diff.\n")
        shutil.rmtree(tmp, ignore_errors=True)
    return {"patched": False, "file": suspect_file, "attempts": attempts,
            "reason": "no model diff made the test suite pass", "strategy": "llm-diff"}
