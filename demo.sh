#!/usr/bin/env bash
# MOLT Forge end-to-end demo: investigate the fixture repo, patch the planted
# bug, verify in the sandbox, emit and check the evidence package.
set -euo pipefail
cd "$(dirname "$0")"

JOBS_DIR="${1:-/tmp/molt-forge-demo-jobs}"
rm -rf "$JOBS_DIR"

# tests/fixtures/sample_repo must itself be a git repo (clone_repo clones
# from it), but git doesn't track a nested .git directory, so a fresh
# checkout of this repo never ships one. Bootstrap it once, idempotently.
FIXTURE="tests/fixtures/sample_repo"
if [ ! -d "$FIXTURE/.git" ]; then
  export GIT_AUTHOR_NAME="molt-forge-fixture" GIT_AUTHOR_EMAIL="fixture@molt-forge.local"
  export GIT_COMMITTER_NAME="molt-forge-fixture" GIT_COMMITTER_EMAIL="fixture@molt-forge.local"
  git -C "$FIXTURE" init -q
  git -C "$FIXTURE" add -A
  git -C "$FIXTURE" commit -q -m "fixture init"
fi

echo "=== 1. Running pipeline on tests/fixtures/sample_repo ==="
python3 -m molt_forge.cli tests/fixtures/sample_repo --jobs-dir "$JOBS_DIR" || true

JOB_DIR=$(find "$JOBS_DIR" -mindepth 1 -maxdepth 1 -type d | head -1)
PKG="$JOB_DIR/package"

echo
echo "=== 2. Evidence package contents ==="
ls -la "$PKG"

echo
echo "=== 3. patch.diff ==="
cat "$PKG/patch.diff"

echo
echo "=== 4. Verdict + artifact hashes (manifest.json) ==="
cat "$PKG/manifest.json"

echo
echo "=== 5. Verifying hash-chained audit log ==="
python3 -m molt_forge.kernel verify "$PKG/events.jsonl"

echo
echo "=== 6. Verifying manifest hashes against files ==="
python3 -c "from molt_forge.evidence import verify_manifest; ok, errs = verify_manifest('$PKG'); print('OK' if ok else errs)"

echo
echo "=== 7. Patched test run transcript (exit code proof) ==="
grep -m1 '\[exit code' "$PKG/patched_test.log"

echo
echo "Demo complete. Evidence zip: $JOB_DIR/*.zip"
