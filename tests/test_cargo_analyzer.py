"""Cargo/libtest failure parsing for the Rust hero (molt-show).

Fixtures below are faithful reconstructions of libtest/rustc output shape
(cargo is not installed in this environment, so they are not byte captures
of a live run); they model the real molt-show hero regression — the
create_genesis protocol-version mismatch — plus compile-error and
library-panic cases.
"""

import unittest

from molt_forge.agents import analyzer
from molt_forge.llm import HeuristicBackend

REPO_FILES = [
    "Cargo.toml",
    "kernel/genesis.rs",
    "kernel/identity.rs",
    "kernel/world.rs",
    "src/lib.rs",
    "tests/genesis_protocol_regression.rs",
    "tests/world.rs",
]

HERO_CARGO_OUTPUT = """\
   Compiling molt-show v0.1.0 (/home/u/molt-show-rehearsal)
    Finished `test` profile [unoptimized + debuginfo] target(s) in 0.42s
     Running unittests src/lib.rs (target/debug/deps/molt_kernel-9f2ab1c4d2e3f4a5)
running 0 tests
test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s

     Running tests/genesis_protocol_regression.rs (target/debug/deps/genesis_protocol_regression-8c1f2b3a4d5e6f7a)
running 1 test
test genesis_envelope_protocol_matches_payload_version ... FAILED

failures:

---- genesis_envelope_protocol_matches_payload_version stdout ----
thread 'genesis_envelope_protocol_matches_payload_version' panicked at tests/genesis_protocol_regression.rs:15:5:
assertion `left == right` failed
  left: "MOLT/0.1"
 right: "MOLT/9.9"


failures:
    genesis_envelope_protocol_matches_payload_version

test result: FAILED. 0 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s

error: test failed, to rerun pass `--test genesis_protocol_regression`
"""

COMPILE_ERROR_OUTPUT = """\
error[E0308]: mismatched types
  --> kernel/genesis.rs:53:21
   |
53 |         protocol: protocol_version,
   |                   ^^^^^^^^^^^^^^^^ expected `&str`, found `String`
   |
   = note: expected reference `&str`
              found struct `String`
error: could not compile `molt-show` (lib) due to 1 previous error
"""

LIBRARY_PANIC_OUTPUT = """\
running 52 tests
test world::inhabitant_tests::chain_survives_restart ... FAILED

failures:

---- world::inhabitant_tests::chain_survives_restart stdout ----
thread 'world::inhabitant_tests::chain_survives_restart' panicked at kernel/world.rs:112:9:
called `Option::unwrap()` on a `None` value

failures:
    world::inhabitant_tests::chain_survives_restart

test result: FAILED. 51 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.01s
"""


class TestCargoAnalyzer(unittest.TestCase):
    def test_hero_assertion_parses(self):
        f = HeuristicBackend().analyze(HERO_CARGO_OUTPUT)
        self.assertEqual(f["failing_tests"],
                         ["genesis_envelope_protocol_matches_payload_version"])
        self.assertEqual(f["failure_kind"], "assertion_failed")
        self.assertIn("MOLT/0.1", f["failure_summary"])
        self.assertIn("MOLT/9.9", f["failure_summary"])
        self.assertEqual(f["failing_test_file"], "tests/genesis_protocol_regression.rs")
        self.assertEqual(f["suspect_line"], 15)
        # panic is in the test file, so the suspect source is left unset for
        # the test->source guess
        self.assertIsNone(f["suspect_file"])

    def test_hero_end_to_end_resolves_kernel_genesis(self):
        f = analyzer.analyze(HeuristicBackend(), HERO_CARGO_OUTPUT, REPO_FILES)
        self.assertEqual(f["failing_test_file"], "tests/genesis_protocol_regression.rs")
        # the test->source guess must land on the real buggy module
        self.assertEqual(f["suspect_file"], "kernel/genesis.rs")

    def test_guess_source_rust_prefix_matching(self):
        files = REPO_FILES
        g = analyzer._guess_source
        self.assertEqual(g("tests/genesis_protocol_regression.rs", files),
                         "kernel/genesis.rs")
        self.assertEqual(g("tests/world.rs", files), "kernel/world.rs")
        # python behavior unchanged
        py = ["calc.py", "tests/test_calc.py"]
        self.assertEqual(g("tests/test_calc.py", py), "calc.py")
        self.assertIsNone(g("tests/test_unknown.py", py))

    def test_compile_error_suspect_is_rustc_span(self):
        f = HeuristicBackend().analyze(COMPILE_ERROR_OUTPUT)
        self.assertEqual(f["failure_kind"], "compile_error")
        self.assertEqual(f["suspect_file"], "kernel/genesis.rs")
        self.assertEqual(f["suspect_line"], 53)
        self.assertIn("mismatched types", f["failure_summary"])

    def test_library_panic_implicates_source_directly(self):
        f = analyzer.analyze(HeuristicBackend(), LIBRARY_PANIC_OUTPUT, REPO_FILES)
        self.assertEqual(f["failing_tests"],
                         ["world::inhabitant_tests::chain_survives_restart"])
        self.assertEqual(f["suspect_file"], "kernel/world.rs")
        self.assertEqual(f["suspect_line"], 112)
        self.assertIsNone(f["failing_test_file"])

    def test_python_output_does_not_misfire_as_cargo(self):
        py_out = ('Traceback (most recent call last):\n'
                  '  File "/tmp/x/calc.py", line 10, in add\n'
                  '    return a + b\n'
                  'TypeError: unsupported operand\n'
                  'FAILED tests/test_calc.py::test_add - TypeError\n')
        f = HeuristicBackend().analyze(py_out)
        self.assertNotIn("failure_kind", f)  # python path keeps its own shape
        self.assertEqual(f["failing_test_file"], "tests/test_calc.py")


if __name__ == "__main__":
    unittest.main()
