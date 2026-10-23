"""Evidence package builder.

Every stage writes artifacts into a package directory; the manifest lists the
sha256 of every file plus the execution-derived verdict. The package is what a
judge downloads and can independently verify.
"""

from __future__ import annotations

import hashlib
import json
import os
import zipfile


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def write(path: str, content: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


def build_manifest(package_dir: str, verdict: str, meta: dict) -> dict:
    artifacts = {}
    for root, _dirs, names in os.walk(package_dir):
        for name in sorted(names):
            if name == "manifest.json":
                continue
            full = os.path.join(root, name)
            rel = os.path.relpath(full, package_dir)
            artifacts[rel] = sha256_file(full)
    manifest = {"verdict": verdict, "artifacts": artifacts, **meta}
    write(os.path.join(package_dir, "manifest.json"),
          json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


def verify_manifest(package_dir: str) -> tuple[bool, list[str]]:
    errors = []
    with open(os.path.join(package_dir, "manifest.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    for rel, digest in manifest.get("artifacts", {}).items():
        full = os.path.join(package_dir, rel)
        if not os.path.exists(full):
            errors.append(f"missing artifact: {rel}")
        elif sha256_file(full) != digest:
            errors.append(f"hash mismatch: {rel}")
    return (not errors), errors


def zip_package(package_dir: str, zip_path: str) -> str:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, names in os.walk(package_dir):
            for name in sorted(names):
                full = os.path.join(root, name)
                zf.write(full, os.path.relpath(full, package_dir))
    return zip_path
