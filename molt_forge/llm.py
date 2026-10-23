"""Pluggable LLM backend.

Priority: Meta Model API (Muse Spark) when META_API_KEY is set; then a local
Ollama server; then the deterministic rule-based fallback that requires NO
network at all.

The fallback is not a stub: it performs real traceback parsing and generates
real candidate source mutations. Verdicts never come from any backend —
only from sandboxed execution (see agents/verifier.py).

NOTE (unverified until the organizer docs land): the Meta endpoint shape
below follows third-party developer guides for api.meta.ai (OpenAI-style
/chat/completions). It is isolated in MetaBackend.generate() so correcting
it is a one-function change; nothing else in the engine depends on it.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
import urllib.error

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.1"

META_API_BASE = os.environ.get("META_API_BASE", "https://api.meta.ai/v1")
META_MODEL = os.environ.get("META_MODEL", "muse-spark-1.3")


class MetaBackend:
    """Muse Spark via the Meta Model API (OpenAI-compatible chat endpoint)."""
    name = f"meta:{META_MODEL}"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("META_API_KEY", "")

    @staticmethod
    def available() -> bool:
        return bool(os.environ.get("META_API_KEY"))

    def generate(self, prompt: str, timeout: float = 120.0) -> str:
        body = json.dumps({
            "model": META_MODEL,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            META_API_BASE.rstrip("/") + "/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        return data["choices"][0]["message"]["content"]

    def analyze(self, test_output: str) -> dict:
        parsed = HeuristicBackend().analyze(test_output)
        try:
            parsed["llm_summary"] = self.generate(
                "Summarize this test failure in two sentences:\n" + test_output[:4000])
        except Exception:
            parsed["llm_summary"] = None
        return parsed

    def mutations(self, source: str, suspect_function: str | None = None):
        # The Meta path patches via unified diffs (agents/patcher_llm.py);
        # mutations remain the heuristic fast path.
        return HeuristicBackend().mutations(source, suspect_function)


class OllamaBackend:
    name = "ollama:llama3.1"

    @staticmethod
    def reachable(timeout: float = 2.0) -> bool:
        try:
            with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=timeout):
                return True
        except Exception:
            return False

    def generate(self, prompt: str, timeout: float = 60.0) -> str:
        body = json.dumps({"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}).encode()
        req = urllib.request.Request(OLLAMA_URL, data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode()).get("response", "")

    def analyze(self, test_output: str) -> dict:
        # Even with an LLM available we keep the deterministic parser as the
        # source of truth for file/line extraction; the LLM only summarizes.
        parsed = HeuristicBackend().analyze(test_output)
        try:
            parsed["llm_summary"] = self.generate(
                "Summarize this test failure in two sentences:\n" + test_output[:4000])
        except Exception:
            parsed["llm_summary"] = None
        return parsed

    def mutations(self, source: str, suspect_function: str | None = None):
        return HeuristicBackend().mutations(source, suspect_function)


# Traceback frame: File "path", line N, in func  (unittest / plain python)
FRAME_RE = re.compile(r'File "([^"]+)", line (\d+), in ([\w<>]+)')
# pytest-style frame: path/to/file.py:LINE: in func
PYTEST_FRAME_RE = re.compile(r'^([\w./-]+\.py):(\d+): in ([\w<>]+)', re.M)
FAIL_RE = re.compile(r'^(?:FAIL|ERROR):\s*(\S+)', re.M)
PYTEST_FAIL_RE = re.compile(r'^FAILED\s+(\S+)', re.M)


# --- Cargo / Rust (libtest + rustc) output ---
CARGO_FAILED_TEST_RE = re.compile(r'^test\s+(\S+)\s+\.\.\.\s+FAILED\s*$', re.M)
CARGO_RESULT_FAILED_RE = re.compile(r'^test result: FAILED\.', re.M)
CARGO_STDOUT_SECTION_RE = re.compile(r'^---- (\S+) stdout ----\s*$', re.M)
CARGO_SECTION_END_RE = re.compile(r'^---- .* ----\s*$', re.M)
CARGO_PANIC_RE = re.compile(r"^thread '[^']+' panicked at ([^:]+):(\d+):(\d+):?\s*$", re.M)
CARGO_ASSERT_RE = re.compile(r'assertion `([^`]+)` failed', re.M)
CARGO_LEFT_RE = re.compile(r'^\s*left:\s*(.+?)\s*$', re.M)
CARGO_RIGHT_RE = re.compile(r'^\s*right:\s*(.+?)\s*$', re.M)
# rustc compile errors: `error[E0308]: ...` with a `--> path:line:col` span
RUSTC_ERROR_RE = re.compile(r'^error(?:\[E\d+\])?:\s*(.+?)\s*$', re.M)
RUSTC_SPAN_RE = re.compile(r'^\s*-->\s+([^\s:]+):(\d+):(\d+)', re.M)


def _analyze_cargo(test_output: str) -> dict | None:
    """Parse `cargo test` / rustc output into the standard findings shape.

    Returns None when the output carries no Rust test-failure signal, so the
    Python parsers below stay in charge for their own stacks.
    """
    failing_tests = sorted(set(CARGO_FAILED_TEST_RE.findall(test_output)))
    has_rust_signal = (CARGO_RESULT_FAILED_RE.search(test_output) is not None
                       or failing_tests
                       or RUSTC_ERROR_RE.search(test_output) is not None)
    if not has_rust_signal:
        return None
    findings = {
        "backend": HeuristicBackend.name,
        "failing_tests": failing_tests,
        "suspect_file": None,
        "suspect_line": None,
        "suspect_function": None,
        "failing_test_file": None,
        "frames": [],
        "failure_kind": None,
        "failure_summary": None,
    }
    # Compile errors first: the suite never ran, so the rustc span is the
    # only honest suspect. A genuine rustc error is always followed by a
    # `--> path:line:col` span; cargo's own tail line ("error: test failed,
    # to rerun pass ...") has no span and must not match.
    compile_error, compile_span = None, None
    for err in RUSTC_ERROR_RE.finditer(test_output):
        span = RUSTC_SPAN_RE.search(test_output, err.end(), err.end() + 400)
        if span:
            compile_error, compile_span = err, span
            break
    if compile_error:
        findings["failure_kind"] = "compile_error"
        findings["failure_summary"] = "compile error: " + compile_error.group(1).strip()[:200]
        findings["suspect_file"] = compile_span.group(1)
        findings["suspect_line"] = int(compile_span.group(2))
        findings["frames"] = [[compile_span.group(1), compile_span.group(2), ""]]
        return findings
    # Test failures: each `---- <test> stdout ----` section carries a panic.
    section_starts = [(m.group(1), m.end()) for m in CARGO_STDOUT_SECTION_RE.finditer(test_output)]
    for idx, (test_name, start) in enumerate(section_starts):
        end = (section_starts[idx + 1][1] if idx + 1 < len(section_starts)
               else len(test_output))
        body = test_output[start:end]
        panic = CARGO_PANIC_RE.search(body)
        if not panic:
            continue
        pfile, pline = panic.group(1), int(panic.group(2))
        # The first non-empty line after the panic header is the message.
        after = test_output[panic.end():].lstrip("\n")
        message = after.split("\n", 1)[0].strip() if after else ""
        kind = "panic"
        summary = message[:200]
        assertion = CARGO_ASSERT_RE.search(body)
        if assertion:
            kind = "assertion_failed"
            left = CARGO_LEFT_RE.search(body)
            right = CARGO_RIGHT_RE.search(body)
            bits = [f"assertion `{assertion.group(1)}` failed"]
            if left:
                bits.append(f"left={left.group(1).strip()}")
            if right:
                bits.append(f"right={right.group(1).strip()}")
            summary = ": ".join(bits)[:300]
        findings["frames"].append([pfile, str(pline), test_name])
        if findings["failure_kind"] is None:
            findings["failure_kind"] = kind
            findings["failure_summary"] = summary
            # A panic inside library code implicates it directly; a panic in
            # the test file leaves suspect_file for the test->source guess.
            if "test" in pfile.lower():
                findings["failing_test_file"] = pfile
                findings["suspect_function"] = test_name
            else:
                findings["suspect_file"] = pfile
                findings["suspect_function"] = test_name
            findings["suspect_line"] = pline
    return findings


class HeuristicBackend:
    """Deterministic, offline, rule-based analysis and patch candidate generation."""
    name = "heuristic-fallback"

    def analyze(self, test_output: str) -> dict:
        # Rust first: cargo/libtest output has its own shape, and parsing it
        # here means MetaBackend and OllamaBackend (which delegate to this)
        # get Rust failures for free, deterministically.
        cargo = _analyze_cargo(test_output)
        if cargo is not None:
            return cargo
        failing_tests = FAIL_RE.findall(test_output) + PYTEST_FAIL_RE.findall(test_output)
        frames = FRAME_RE.findall(test_output)
        frames += [(m.group(1), m.group(2), m.group(3)) for m in PYTEST_FRAME_RE.finditer(test_output)]
        test_frames = [f for f in frames if "test" in f[0].lower()]
        src_frames = [f for f in frames if "test" not in f[0].lower()]
        suspect_file = src_frames[-1][0] if src_frames else None
        suspect_line = int(src_frames[-1][1]) if src_frames else None
        suspect_function = src_frames[-1][2] if src_frames else None
        failing_test_file = test_frames[0][0] if test_frames else None
        if not failing_test_file:
            for ft in failing_tests:
                path = ft.split("::")[0].split(" ")[0]
                if path.endswith(".py"):
                    failing_test_file = path
                    break
        return {
            "backend": self.name,
            "failing_tests": sorted(set(failing_tests)),
            "suspect_file": suspect_file,
            "suspect_line": suspect_line,
            "suspect_function": suspect_function,
            "failing_test_file": failing_test_file,
            "frames": [list(f) for f in frames],
        }

    # --- candidate mutation patterns: (description, compiled regex, replacement) ---
    PATTERNS = [
        ("slice end `x - 1` -> `x` (off-by-one in slice)", re.compile(r'\s*-\s*1\s*\]'), ']'),
        ("`range(len(x) - 1)` -> `range(len(x))`", re.compile(r'range\(len\((\w+)\)\s*-\s*1\)'), r'range(len(\1))'),
        ("`range(n - 1)` -> `range(n)`", re.compile(r'range\((\w+)\s*-\s*1\)'), r'range(\1)'),
        ("`< len(` -> `<= len(`", re.compile(r'<\s*len\('), '<= len('),
        ("`> 0` -> `>= 0`", re.compile(r'>\s*0(?!\d)'), '>= 0'),
        ("`+ 1` -> `- 1`", re.compile(r'\+\s*1(?!\d)'), '- 1'),
        ("`- 1` -> `+ 1`", re.compile(r'-\s*1(?!\d)(?!\s*\])'), '+ 1'),
    ]

    def mutations(self, source: str, suspect_function: str | None = None):
        """Yield (description, mutated_source) candidates: one substitution each."""
        candidates = []
        for desc, rx, repl in self.PATTERNS:
            for m in rx.finditer(source):
                mutated = source[:m.start()] + rx.sub(repl, source[m.start():m.end()], count=1) + source[m.end():]
                if mutated != source:
                    candidates.append((f"{desc} at offset {m.start()}", mutated))
            if len(candidates) >= 25:
                break
        return candidates


def get_backend():
    """Meta (if keyed) > Ollama (if reachable) > deterministic heuristic."""
    if MetaBackend.available():
        return MetaBackend()
    if OllamaBackend.reachable():
        return OllamaBackend()
    return HeuristicBackend()
