# MOLT Forge

MOLT Forge takes an unfamiliar git repository, investigates it, writes a real
patch with a regression test, runs the tests in an isolated sandbox, and hands
you a hash-identified, downloadable evidence package.

**Honesty rule:** every claim is backed by execution evidence. The verdict is
decided only by sandboxed test exit codes — never by anything an AI model says.
Verdicts: `validated` · `proposed-unverified` · `diagnosis-only` · `documented-failure`.

## Setup (for a non-technical user)

You need a Linux laptop with Python 3.11+ and git installed.

1. Open a terminal in this folder (the one containing this README).
2. Install the one required Python package:

   ```
   pip install -r requirements.txt
   ```

   (If you have no internet, everything except the web API still works:
   the CLI and demo need only the Python standard library.)

3. Run the demo to prove everything works:

   ```
   ./demo.sh
   ```

   It investigates a tiny sample repo with a planted bug, patches it, runs
   the tests before and after, and prints the verdict and the evidence
   package location.

## Using it on a repository

**Command line (no server needed):**

```
python -m molt_forge.cli <repo-url-or-local-path>
```

Example: `python -m molt_forge.cli tests/fixtures/sample_repo`

It prints progress, the verdict, and the path to the evidence package
(a folder plus a `.zip`). The exit code is 0 only when the verdict is
`validated`.

**Web UI (for judges):**

```
python -m molt_forge.api
```

Then open http://127.0.0.1:5000 in a browser. Paste a repo URL, watch live
progress, explore the investigation map (the spinning globe — click nodes for
evidence), inspect the diff and the manifest hashes, and download the evidence
zip. The UI works offline: three.js is vendored in `web/vendor/`, and if it is
missing the globe falls back to a plain-canvas 3D projection.

## What is in an evidence package

- `patch.diff` — a real unified diff against the pinned commit
- `regression_test.py` — the test that failed before the patch and passes after
- `baseline_test.log` / `patched_test.log` — captured test output with exit codes
- `events.jsonl` — hash-chained, append-only audit log of every stage
- `graph.json` — the investigation graph (repos, modules, findings, artifacts)
- `manifest.json` — sha256 of every artifact + the verdict

## Verifying evidence yourself

```
python -m molt_forge.kernel verify <package>/events.jsonl   # audit-log chain
python -c "from molt_forge.evidence import verify_manifest; print(verify_manifest('<package>'))"
```

## Optional: local AI

If you run Ollama locally (`ollama serve`, model `llama3.1`), MOLT Forge will
use it for analysis summaries. Without it, a deterministic rule-based engine
does the analysis and patch generation — no network required.

## Safety

Untrusted repository code runs only inside `molt_forge/sandbox.py`: a
subprocess in a throwaway temp copy, with CPU/memory limits, a scrubbed
environment (no credentials, proxies, or host variables) and a hard timeout.

## Tests

```
python -m pytest tests/
```
