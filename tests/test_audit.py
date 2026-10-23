"""Audit mode + cargo parsing: issue-driven repair on a passing suite."""

import os
import subprocess
import tempfile
import unittest

from molt_forge.agents import analyzer
from molt_forge.pipeline import run_pipeline

CALC = '''"""Latent-bug library: suite passes, first_n is still wrong."""


def first_n(items, n):
    """Return the first n items of the sequence."""
    return items[:n - 1]


def clamp(value, low, high):
    return max(low, min(high, value))
'''

WEAK_TESTS = '''from calc import clamp, first_n


def test_clamp():
    assert clamp(5, 0, 3) == 3


def test_first_n_beyond_end():
    assert first_n([1, 2, 3], 5) == [1, 2, 3]
'''

AUDIT_DIFF = """--- a/calc.py
+++ b/calc.py
@@ -4,3 +4,3 @@
 def first_n(items, n):
     \"\"\"Return the first n items of the sequence.\"\"\"
-    return items[:n - 1]
+    return items[:n]
--- /dev/null
+++ b/tests/test_regression.py
@@ -0,0 +1,5 @@
+from calc import first_n
+
+
+def test_first_n_exact():
+    assert first_n([1, 2, 3], 2) == [1, 2]
"""

CARGO_OUT = """running 3 tests
test kernel::genesis::tests::envelope_matches_payload ... FAILED

failures:

---- kernel::genesis::tests::envelope_matches_payload stdout ----
thread 'kernel::genesis::tests::envelope_matches_payload' panicked at kernel/genesis.rs:53:5:
assertion `left == right` failed

failures:
    kernel::genesis::tests::envelope_matches_payload

test result: FAILED. 50 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out
"""


class FakeBackend:
    name = "fake-model"

    def __init__(self, response):
        self.response = response

    def generate(self, prompt):
        return self.response


def _make_repo(root):
    repo = os.path.join(root, "audit_repo")
    os.makedirs(os.path.join(repo, "tests"))
    with open(os.path.join(repo, "calc.py"), "w") as fh:
        fh.write(CALC)
    with open(os.path.join(repo, "conftest.py"), "w") as fh:
        fh.write("")
    with open(os.path.join(repo, "tests", "test_calc.py"), "w") as fh:
        fh.write(WEAK_TESTS)
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    subprocess.run(["git", "init", "-q"], cwd=repo, env=env, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, env=env, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, env=env, check=True)
    return repo


class TestCargoParsing(unittest.TestCase):
    def test_cargo_failure_parsed(self):
        from molt_forge.llm import HeuristicBackend
        findings = analyzer.analyze(HeuristicBackend(), CARGO_OUT,
                                    ["kernel/genesis.rs", "tests/world.rs"])
        self.assertEqual(findings["suspect_file"], "kernel/genesis.rs")
        self.assertEqual(findings["suspect_line"], 53)
        self.assertIn("kernel::genesis::tests::envelope_matches_payload",
                      findings["failing_tests"])


class TestAuditMode(unittest.TestCase):
    def test_latent_bug_validated_via_regression_differential(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(tmp)
            job = run_pipeline(repo, os.path.join(tmp, "jobs"),
                               issue="first_n returns one fewer item than requested",
                               suspect_hint="calc.py",
                               backend=FakeBackend(AUDIT_DIFF))
            self.assertEqual(job["verdict"], "validated", job.get("error"))
            self.assertTrue(job["skeptic"]["accept"], job["skeptic"])
            self.assertEqual(job["skeptic"]["differential"]["method"],
                             "test-only diff applied to unpatched tree")

    def test_non_discriminating_patch_rejected(self):
        weak_diff = AUDIT_DIFF.replace("== [1, 2]", "in ([1, 2], [1])")
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(tmp)
            job = run_pipeline(repo, os.path.join(tmp, "jobs"),
                               issue="first_n returns one fewer item than requested",
                               suspect_hint="calc.py",
                               backend=FakeBackend(weak_diff))
            self.assertNotEqual(job["verdict"], "validated")
            self.assertFalse(job["skeptic"]["accept"])


if __name__ == "__main__":
    unittest.main()
