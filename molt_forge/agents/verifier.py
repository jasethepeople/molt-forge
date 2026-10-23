"""Verifier agent: the ONLY component allowed to assign verdicts.

Verdicts are derived exclusively from sandboxed execution exit codes:
  validated            - baseline failed, patch applied, suite passes after patch
  proposed-unverified  - a patch was produced but the post-patch suite did not pass
  diagnosis-only       - no patch produced; analysis findings only
  documented-failure   - the pipeline itself could not complete a stage
"""

from __future__ import annotations

import os
import shutil

from .. import sandbox

VALIDATED = "validated"
PROPOSED_UNVERIFIED = "proposed-unverified"
DIAGNOSIS_ONLY = "diagnosis-only"
DOCUMENTED_FAILURE = "documented-failure"
VERDICTS = {VALIDATED, PROPOSED_UNVERIFIED, DIAGNOSIS_ONLY, DOCUMENTED_FAILURE}


def run_suite(repo_dir: str, timeout: int | None = None) -> "sandbox.SandboxResult":
    """Run the repo's test suite inside the sandbox (on a throwaway copy)."""
    from .. import stacks
    env = stacks.run_envelope(repo_dir)
    return sandbox.run_in_copy(repo_dir, sandbox.test_command(repo_dir),
                               timeout=timeout or env["timeout"],
                               cpu_seconds=env["cpu_seconds"], mem_mb=env["mem_mb"])


def run_suite_on_patched(repo_dir: str, patched_file: str, patched_source: str,
                         dest_dir: str, timeout: int | None = None) -> "sandbox.SandboxResult":
    """Materialize the patched tree and run the suite in the sandbox."""
    from .. import stacks
    if os.path.exists(dest_dir):
        shutil.rmtree(dest_dir)
    shutil.copytree(repo_dir, dest_dir)
    with open(os.path.join(dest_dir, patched_file), "w", encoding="utf-8") as fh:
        fh.write(patched_source)
    env = stacks.run_envelope(dest_dir)
    return sandbox.run_in_copy(dest_dir, sandbox.test_command(dest_dir),
                               timeout=timeout or env["timeout"],
                               cpu_seconds=env["cpu_seconds"], mem_mb=env["mem_mb"])


def run_suite_on_patched_files(repo_dir: str, patched_files: dict, dest_dir: str,
                               timeout: int | None = None) -> "sandbox.SandboxResult":
    """Materialize a multi-file patch (LLM diff path) and run the suite."""
    from .. import stacks
    if os.path.exists(dest_dir):
        shutil.rmtree(dest_dir)
    shutil.copytree(repo_dir, dest_dir)
    for rel, source in patched_files.items():
        full = os.path.join(dest_dir, rel)
        os.makedirs(os.path.dirname(full) or dest_dir, exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(source)
    env = stacks.run_envelope(dest_dir)
    return sandbox.run_in_copy(dest_dir, sandbox.test_command(dest_dir),
                               timeout=timeout or env["timeout"],
                               cpu_seconds=env["cpu_seconds"], mem_mb=env["mem_mb"])


def decide(baseline: "sandbox.SandboxResult | None", patch_info: dict | None,
           post: "sandbox.SandboxResult | None", pipeline_error: str | None = None) -> str:
    if pipeline_error:
        return DOCUMENTED_FAILURE
    if patch_info and patch_info.get("patched"):
        if post is not None and post.ok and baseline is not None and not baseline.ok:
            return VALIDATED
        return PROPOSED_UNVERIFIED
    return DIAGNOSIS_ONLY
