import os
import tempfile
import unittest

from molt_forge import evidence
from molt_forge.agents import verifier


class TestEvidence(unittest.TestCase):
    def test_manifest_hashes_match_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            evidence.write(os.path.join(tmp, "patch.diff"), "--- a/x\n+++ b/x\n")
            evidence.write(os.path.join(tmp, "log.txt"), "hello\n")
            manifest = evidence.build_manifest(tmp, "validated", {"job_id": "t"})
            self.assertIn("patch.diff", manifest["artifacts"])
            self.assertIn("log.txt", manifest["artifacts"])
            self.assertIn("manifest.json", os.listdir(tmp))
            ok, errors = evidence.verify_manifest(tmp)
            self.assertTrue(ok, errors)
            # tamper -> verification fails
            evidence.write(os.path.join(tmp, "log.txt"), "tampered\n")
            ok, errors = evidence.verify_manifest(tmp)
            self.assertFalse(ok)

    def test_verdict_values(self):
        self.assertEqual(verifier.VERDICTS, {
            "validated", "proposed-unverified", "diagnosis-only", "documented-failure"})

    def test_verifier_never_validates_without_execution(self):
        # patch claimed but no execution results -> cannot be validated
        v = verifier.decide(None, {"patched": True}, None)
        self.assertEqual(v, "proposed-unverified")
        v = verifier.decide(None, None, None, pipeline_error="boom")
        self.assertEqual(v, "documented-failure")
        v = verifier.decide(None, None, None)
        self.assertEqual(v, "diagnosis-only")


if __name__ == "__main__":
    unittest.main()
