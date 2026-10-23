#!/usr/bin/env bash
# MOLT Forge end-to-end demo: investigate the fixture repo, patch the planted
# bug, verify in the sandbox, emit and check the evidence package.
set -euo pipefail
cd "$(dirname "$0")"

JOBS_DIR="${1:-/tmp/molt-forge-demo-jobs}"
rm -rf "$JOBS_DIR"

echo "=== 1. Running pipeline on tests/fixtures/sample_repo ==="
python -m molt_forge.cli tests/fixtures/sample_repo --jobs-dir "$JOBS_DIR" || true

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
python -m molt_forge.kernel verify "$PKG/events.jsonl"

echo
echo "=== 6. Verifying manifest hashes against files ==="
python -c "from molt_forge.evidence import verify_manifest; ok, errs = verify_manifest('$PKG'); print('OK' if ok else errs)"

echo
echo "=== 7. Patched test run transcript (exit code proof) ==="
grep -m1 '\[exit code' "$PKG/patched_test.log"

echo
echo "Demo complete. Evidence zip: $JOB_DIR/*.zip"
