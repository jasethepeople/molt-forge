"""Dress rehearsal for the hero run (offline, scripted model stand-in).

Drives the REAL audit pipeline against a molt-show clone: baseline cargo
test (green), issue stated, scripted 'model' returns the proven rehearsal
diff (genesis fix + regression test), Skeptic test-only differential gates
the verdict. When META_API_KEY exists, swap ScriptedBackend for the real
MetaBackend and this becomes the live hero run.
"""
import difflib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from molt_forge.pipeline import run_pipeline  # noqa: E402

ORIG = os.path.expanduser("~/workspace/verify-molt-show")
FIXED = os.path.expanduser("~/workspace/molt-show-rehearsal")


def build_diff() -> str:
    with open(os.path.join(ORIG, "kernel/genesis.rs")) as fh:
        orig = fh.read()
    with open(os.path.join(FIXED, "kernel/genesis.rs")) as fh:
        fixed = fh.read()
    d1 = "".join(difflib.unified_diff(
        orig.splitlines(keepends=True), fixed.splitlines(keepends=True),
        fromfile="a/kernel/genesis.rs", tofile="b/kernel/genesis.rs"))
    with open(os.path.join(FIXED, "tests/genesis_protocol_regression.rs")) as fh:
        reg = fh.read()
    d2 = "".join(difflib.unified_diff(
        [], reg.splitlines(keepends=True),
        fromfile="/dev/null", tofile="b/tests/genesis_protocol_regression.rs"))
    return d1 + d2


class ScriptedBackend:
    name = "scripted-muse-stand-in"

    def __init__(self, diff):
        self._diff = diff

    def generate(self, prompt):
        return self._diff


if __name__ == "__main__":
    job = run_pipeline(
        ORIG, os.path.expanduser("~/workspace/drill_jobs"), job_id="hero1",
        issue=("create_genesis writes the event envelope protocol as a hardcoded "
               "\"MOLT/0.1\" while the genesis payload carries the caller-supplied "
               "protocol_version; whenever they differ, the envelope and payload "
               "disagree about the protocol version."),
        suspect_hint="kernel/genesis.rs",
        backend=ScriptedBackend(build_diff()),
        log=lambda m: print(m, flush=True))
    print("\nVERDICT:", job["verdict"], "| status:", job["status"])
    print("skeptic:", job.get("skeptic"))
    print("package:", job["package_dir"])
