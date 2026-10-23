# BUILD LOG — MOLT Forge: The Unkillable Repair

Working tree: `~/workspace/molt-forge-build/` (forked from the audited v1.0 zip
2026-10-21; the original zip and audit copy are untouched).
Baseline on fork: 6/6 tests green. After Sprint 1: **17/17 green.**

## Sprint 1 — 2026-10-21 (pre-kickoff prep; user ruling: "build The Unkillable Repair")

1. **Analyzer guard** (`agents/analyzer.py`) — a suspect file not present in the
   repo inventory is rejected as a parser artifact (`suspect_rejected`), fixing
   the audited `<frozen runpy>` collapse.
2. **Stack command table** (`stacks.py`) — manifest→test-command + resource
   envelope: Cargo.toml→`cargo test` (900s/600cpu/4GB), package.json test
   script→`npm test`, Python→pytest/unittest as before. `sandbox.test_command`
   and `intake.has_tests` now delegate to it; Forge is no longer Python-blind
   (a Cargo repo now has "tests" because its manifest says so).
3. **Signed event log** (`signing.py`, `kernel.py`) — Ed25519 identities per
   agent role (orchestrator/planner/fixer/skeptic/verifier). Keys persist in
   `<job>/identities.json` (job dir only, never packaged; pubkeys are in the
   manifest). Signed events verify offline; tampered payloads and bad
   signatures fail `kernel verify`.
4. **MetaBackend** (`llm.py`) — Muse Spark via Meta Model API, env-gated
   (`META_API_KEY`, `META_API_BASE`, `META_MODEL`); priority Meta > Ollama >
   heuristic. Endpoint shape follows third-party guides and is isolated in
   one function — UNVERIFIED until organizer docs land at kickoff.
5. **Model diff patcher** (`agents/patcher_llm.py`) — prompts the model for a
   unified diff, applies it with a built-in exact-context applier, accepts
   only a suite-passing candidate, bounded retries (3) with failure feedback.
   Mutation patcher remains the offline Python fast path.
6. **Differential Skeptic** (`agents/skeptic.py`) — scope check (diff may touch
   the suspect file + test files only) and fail-before/pass-after differential;
   when the patch carries test changes, the test-only diff is applied to a
   pristine tree and must FAIL there. Skeptic rejection downgrades
   validated → proposed-unverified. Report lands in the package as skeptic.json.
7. **Succession** (`pipeline.py`, `cli.py`) — `--stop-after patch` checkpoints
   full run state (`state.json`) and signs an `interrupted` event; a separate
   process running `--resume <job>` replays the signed log, re-derives state,
   verifies, runs the Skeptic, and packages. Resume is idempotent (a completed
   job is a no-op).

## Verified live (two-process drill, 2026-10-21)

```
$ cli tests/fixtures/sample_repo --job-id drill1 --stop-after patch   # process 1 exits
$ cli --resume drill1                                                  # process 2, cold
status: done   verdict: validated
chain: stage -> intake -> stage -> baseline -> llm_backend -> analysis
       -> patch_attempts -> patch -> interrupted -> resumed
       -> verification -> skeptic -> verdict -> package
$ kernel verify package/events.jsonl  -> OK (hash chain + signatures)
$ sed tamper one exit_code            -> FAILED (hash mismatch), exit 1
```

Drill artifacts: `~/workspace/drill_jobs/drill1/` (package is downloadable proof).

## Prep work — 2026-10-21 (post-Sprint 1, pre-kickoff)

8. **Cargo failure parser** (`molt_forge/llm.py`, `molt_forge/agents/analyzer.py`,
   `tests/test_cargo_analyzer.py`) — the analyzer is no longer Python-blind:
   `HeuristicBackend.analyze` now parses `cargo test` output deterministically
   (so MetaBackend/OllamaBackend, which delegate, get it too). Parses the
   libtest `test ... FAILED` lines, each `---- <test> stdout ----` panic
   section (panic location, assertion `left == right` failed with the actual
   left/right values), rustc compile errors (distinguished from cargo's own
   `error: test failed, to rerun ...` tail line by requiring the `-->`
   span), and panics inside library code (e.g. `.unwrap()` in `kernel/`)
   which implicate the source file directly. Test→source guessing extended
   for Rust: `tests/genesis_protocol_regression.rs` resolves to
   `kernel/genesis.rs` (full stem, then progressively shorter underscore
   prefixes). Suite now **23/23 green** (17 + 6 new).

## Sprint 2 — 2026-10-21 (spikes + hero loop mechanics)

- **Spikes executed** (full results: `~/workspace/your_files/unkillable-repair-spike-results.md`):
  AetherState boot PASS with apt-installed Redis/PostgreSQL (bridge :8080, MCP :3000,
  /health 200, /metrics 401 unauthenticated). Jason-OS slice FAIL as shipped (root
  cause: `GHOST_KEY_TTL_MS = 0`, privacy-kernel.ts:37 — see spike doc); Plan B active.
- **Cargo analysis**: `HeuristicBackend` parses libtest/rustc output (failing tests,
  panic spans, assertion left/right, compile-error spans) into `failure_kind` /
  `failure_summary` findings; `analyzer._guess_source` generalizes test→source
  mapping to Rust (genesis_protocol_regression → kernel/genesis). Spec:
  `tests/test_cargo_analyzer.py`. (These files landed via a background pass at
  12:49; verified + integrated in this sprint.)
- **Audit mode** (`pipeline.run_pipeline(issue=..., suspect_hint=...)`): issue-driven
  repair for suites that PASS but carry a latent defect — the molt-show hero shape.
  Verdict gate is the Skeptic's test-only differential (regression in the diff must
  fail on the unpatched tree, pass on the patched one). CLI: `--issue/--suspect`.
  Resume supports audit checkpoints.
- **parse_diff hardened**: hunk bodies consumed by @@ line counts (a following
  file's `--- ` header can no longer be swallowed into the previous hunk).
- Suite: **26/26 green** (6 v1 + 11 succession + 6 cargo spec + 3 audit).
- **Dress rehearsal PASSED** (`scripts/dress_rehearsal.py`, job `hero1` in
  `~/workspace/drill_jobs/`): scripted model stand-in returned the proven rehearsal
  diff; the full audit pipeline ran against a molt-show clone — baseline green (51),
  candidate accepted, verify green (**52 passed**), Skeptic test-only differential
  (fails on unpatched tree exit 101, passes patched), **verdict: validated**, signed
  chain verifies. Swap in MetaBackend when the API key lands and it becomes the
  live hero run.
- **Two sandbox bugs the rehearsal caught** (both would have detonated live):
  (1) scrubbed HOME made rustup unable to find its toolchain → `clean_env` now
  carries RUSTUP_HOME/CARGO_HOME (build caches, not credentials); (2) sandbox temp
  copies in /tmp (512M tmpfs) overflowed during cargo linking (ld bus error) →
  all temp dirs now under `~/.cache/molt-forge` via `sandbox.sandbox_tmpdir()`.

## Still open (prep days Oct 22–25 / hackathon Days 1–3)

- Meta API: confirm endpoint/model string against organizer docs; first live
  Muse call must be logged with prompt/response hashes (manifest v2).
  **User-side blocker: create the Meta Model API key** (~10 min).
- Real sandbox isolation (Modal) — local runs still use the bounded
  subprocess; demo machine posture is localhost-only.
  **User-side blocker: create the Modal free-tier account** (~15 min).
- Web UI: `/package-file` endpoint + patch view (known v1 bug), room view,
  tamper button, kill button wired to the CLI/API stop/resume flow.
- AetherState E2E mutation→persistence round trip (Day-2 test, not a scope blocker).
- `demo.sh` still defaults its jobs dir to /tmp on the build copy — fix before
  any machine with a small /tmp matters.

## Web polish adoption (2026-10-23)
- External polish pass audited + adopted: 3D globe (globe.js + vendored
  three.min.js) removed; web/graph.js findings-list UI renders every graph
  node kind (repo/module/finding/artifact/agent) with a fallback group.
- /api/jobs/<id>/package-file endpoint added (traversal-guarded); the web
  client now actually fetches patch.diff through it (the old stub was dead).
- Fixture bootstrap: conftest.py and demo.sh git-init
  tests/fixtures/sample_repo when its .git is missing (a fresh clone of
  this repo never ships the nested .git). Idempotent.
- demo.sh now calls python3 (bare `python` is absent on python3-only hosts).
- Verified cold from the polish tree before adopting: pytest 26/26,
  demo.sh verdict "validated", hash chain + manifest OK; core engine
  files byte-identical to the pre-polish tree.
