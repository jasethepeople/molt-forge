import json
import os
import tempfile
import unittest

from molt_forge import evidence
from molt_forge.kernel import EventLog
from molt_forge.pipeline import run_pipeline

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "fixtures", "sample_repo")


class TestPipeline(unittest.TestCase):
    def test_end_to_end_produces_validated_patch(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = run_pipeline(FIXTURE, tmp)
            self.assertEqual(job["status"], "done")
            self.assertEqual(job["verdict"], "validated", job.get("error"))

            pkg = job["package_dir"]
            # real unified diff against the pinned commit
            with open(os.path.join(pkg, "patch.diff")) as fh:
                diff = fh.read()
            self.assertIn("--- a/calc.py", diff)
            self.assertIn("+++ b/calc.py", diff)
            self.assertIn("-    return items[:n - 1]", diff)
            self.assertIn("+    return items[:n]", diff)

            # real regression test + captured logs with exit codes
            self.assertTrue(os.path.exists(os.path.join(pkg, "regression_test.py")))
            with open(os.path.join(pkg, "baseline_test.log")) as fh:
                self.assertIn("[exit code:", fh.read())
            with open(os.path.join(pkg, "patched_test.log")) as fh:
                self.assertIn("[exit code: 0]", fh.read())

            # manifest hashes verify
            ok, errors = evidence.verify_manifest(pkg)
            self.assertTrue(ok, errors)
            self.assertEqual(job["manifest"]["verdict"], "validated")
            self.assertTrue(job["manifest"]["pinned_sha"])

            # event log chain verifies
            ok, errors = EventLog.verify_file(os.path.join(pkg, "events.jsonl"))
            self.assertTrue(ok, errors)

            # zip exists and contains the manifest
            self.assertTrue(os.path.exists(job["zip_path"]))
            import zipfile
            with zipfile.ZipFile(job["zip_path"]) as zf:
                self.assertIn("manifest.json", zf.namelist())


if __name__ == "__main__":
    unittest.main()
