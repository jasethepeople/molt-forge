import json
import os
import tempfile
import unittest

from molt_forge.kernel import EventLog


class TestKernel(unittest.TestCase):
    def test_hash_chain_integrity_and_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "events.jsonl")
            log = EventLog(path)
            log.append("a", {"x": 1})
            log.append("b", {"y": 2})
            ok, errors = EventLog.verify_file(path)
            self.assertTrue(ok, errors)

            # resume: new EventLog over the same file continues the chain
            log2 = EventLog(path)
            self.assertEqual(log2.last_hash, log.last_hash)
            ev = log2.append("c", {"z": 3})
            self.assertEqual(ev["seq"], 2)
            self.assertEqual(ev["prev_hash"], log.last_hash)
            ok, errors = EventLog.verify_file(path)
            self.assertTrue(ok, errors)

    def test_tamper_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "events.jsonl")
            log = EventLog(path)
            log.append("a", {"x": 1})
            log.append("b", {"y": 2})
            with open(path) as fh:
                lines = fh.readlines()
            ev = json.loads(lines[0])
            ev["payload"]["x"] = 999  # tamper
            lines[0] = json.dumps(ev, sort_keys=True) + "\n"
            with open(path, "w") as fh:
                fh.writelines(lines)
            ok, errors = EventLog.verify_file(path)
            self.assertFalse(ok)
            self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
