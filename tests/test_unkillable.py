"""Unkillable Repair additions: stacks, analyzer guard, signed events,
LLM diff patcher, differential Skeptic, and kill/resume succession."""

import json
import os
import tempfile
import unittest

from molt_forge import evidence, stacks
from molt_forge.agents import analyzer, patcher_llm, skeptic
from molt_forge.kernel import EventLog
from molt_forge.pipeline import resume_pipeline, run_pipeline
from molt_forge.signing import Identity, IdentityStore

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "fixtures", "sample_repo")

GOOD_DIFF = """--- a/calc.py
+++ b/calc.py
@@ -4,3 +4,3 @@
 def first_n(items, n):
     \"\"\"Return the first n items of the sequence.\"\"\"
-    return items[:n - 1]
+    return items[:n]
"""


class FakeBackend:
    name = "fake-model"

    def __init__(self, response):
        self.response = response

    def generate(self, prompt):
        return self.response


class TestStacks(unittest.TestCase):
    def test_rust_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "Cargo.toml"), "w").close()
            spec = stacks.detect_stack(tmp)
            self.assertEqual(spec["stack"], "rust")
            self.assertEqual(spec["test_command"], ["cargo", "test"])

    def test_node_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "package.json"), "w") as fh:
                json.dump({"scripts": {"test": "vitest run"}}, fh)
            self.assertEqual(stacks.detect_stack(tmp)["stack"], "node")

    def test_python_fixture(self):
        self.assertEqual(stacks.detect_stack(FIXTURE)["stack"], "python")


class TestAnalyzerGuard(unittest.TestCase):
    def test_frozen_runpy_suspect_rejected(self):
        class B:
            name = "b"

            def analyze(self, out):
                return {"failing_tests": ["t"], "suspect_file": "<frozen runpy>",
                        "suspect_line": 1, "suspect_function": "<module>",
                        "failing_test_file": None, "frames": []}

        findings = analyzer.analyze(B(), "out", ["calc.py", "tests/test_calc.py"])
        self.assertIsNone(findings["suspect_file"])
        self.assertEqual(findings["suspect_rejected"], "<frozen runpy>")


class TestSignedLog(unittest.TestCase):
    def test_signed_chain_verifies_and_tamper_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = IdentityStore(os.path.join(tmp, "ids.json"))
            log = EventLog(os.path.join(tmp, "events.jsonl"))
            log.append("verdict", {"verdict": "validated"}, signer=store.get("verifier"))
            ok, errors = EventLog.verify_file(log.path)
            self.assertTrue(ok, errors)
            text = open(log.path).read().replace("validated", "validated!")
            open(log.path, "w").write(text)
            ok, errors = EventLog.verify_file(log.path)
            self.assertFalse(ok)

    def test_identity_survives_store_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ids.json")
            pub1 = IdentityStore(path).get("fixer").pub_hex
            pub2 = IdentityStore(path).get("fixer").pub_hex
            self.assertEqual(pub1, pub2)


class TestLlmPatcher(unittest.TestCase):
    def test_model_diff_accepted_when_suite_passes(self):
        info = patcher_llm.generate_patch_with_model(
            FIXTURE, "calc.py", "FAILED tests/test_calc.py", FakeBackend(GOOD_DIFF),
            failing_test_file="tests/test_calc.py")
        self.assertTrue(info["patched"], info)
        self.assertIn("items[:n]", info["patched_source"])

    def test_extract_diff_from_fenced_reply(self):
        diff = patcher_llm.extract_diff("Here you go:\n```diff\n" + GOOD_DIFF + "```\n")
        self.assertTrue(diff.startswith("--- a/calc.py"))


class TestSkeptic(unittest.TestCase):
    def _patch_info(self):
        return patcher_llm.generate_patch_with_model(
            FIXTURE, "calc.py", "FAILED", FakeBackend(GOOD_DIFF),
            failing_test_file="tests/test_calc.py")

    def test_accepts_clean_patch_with_differential_evidence(self):
        from molt_forge.agents import verifier
        baseline = verifier.run_suite(FIXTURE)
        info = self._patch_info()
        post = verifier.run_suite_on_patched(
            FIXTURE, info["file"], info["patched_source"],
            tempfile.mkdtemp(prefix="skeptic_post_"))
        review = skeptic.review(FIXTURE, info, baseline, post)
        self.assertTrue(review["scope_ok"], review)
        self.assertTrue(review["accept"], review)

    def test_rejects_out_of_scope_diff(self):
        info = self._patch_info()
        info["diff"] = info["diff"].replace("calc.py", "secret.py")
        info["file"] = "calc.py"
        from molt_forge import sandbox
        fake = sandbox.SandboxResult(["x"], 0, "", "", False, 0.0)
        base = sandbox.SandboxResult(["x"], 1, "", "", False, 0.0)
        review = skeptic.review(FIXTURE, info, base, fake)
        self.assertFalse(review["scope_ok"])
        self.assertFalse(review["accept"])


class TestSuccession(unittest.TestCase):
    def test_kill_after_patch_then_resume_validates(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = run_pipeline(FIXTURE, tmp, job_id="drill", stop_after="patch")
            self.assertEqual(job["status"], "interrupted")
            self.assertIsNone(job["verdict"])
            job2 = resume_pipeline(tmp, "drill")
            self.assertEqual(job2["status"], "done")
            self.assertEqual(job2["verdict"], "validated", job2.get("error"))
            ok, errors = EventLog.verify_file(
                os.path.join(job2["package_dir"], "events.jsonl"))
            self.assertTrue(ok, errors)
            types = [json.loads(l)["type"] for l in
                     open(os.path.join(job2["package_dir"], "events.jsonl"))]
            self.assertIn("interrupted", types)
            self.assertIn("resumed", types)
            # signed by real agent roles, pubkeys published in the manifest
            self.assertIn("fixer", job2["manifest"]["agent_pubkeys"])
            self.assertTrue(os.path.exists(os.path.join(job2["package_dir"], "skeptic.json")))
            ok, errors = evidence.verify_manifest(job2["package_dir"])
            self.assertTrue(ok, errors)


if __name__ == "__main__":
    unittest.main()
