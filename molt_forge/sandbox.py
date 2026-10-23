"""Sandboxed execution of untrusted repository code.

Everything untrusted runs here: a subprocess whose cwd is a throwaway copy of
the tree, with CPU/memory rlimits, a scrubbed environment (no proxies, no
credentials, no host env leakage) and a hard wall-clock timeout.
"""

from __future__ import annotations

import os
import resource
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

SAFE_ENV = {
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONHASHSEED": "0",
    "NO_PROXY": "*",
    "no_proxy": "*",
}


@dataclass
class SandboxResult:
    argv: list
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool
    duration_s: float
    workdir: str = field(default="")

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    def transcript(self) -> str:
        rc = "TIMEOUT" if self.timed_out else str(self.returncode)
        return (f"$ {' '.join(self.argv)}\n[exit code: {rc}] [duration: {self.duration_s:.2f}s]\n"
                f"--- stdout ---\n{self.stdout}\n--- stderr ---\n{self.stderr}")


def _limits(cpu_seconds: int, mem_bytes: int):
    def apply():
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        try:
            resource.setrlimit(resource.RLIMIT_NPROC, (256, 256))
        except (ValueError, OSError):
            pass
    return apply


def clean_env(tmp_home: str) -> dict:
    env = dict(SAFE_ENV)
    env["PATH"] = os.environ.get("PATH", "/usr/bin:/bin")
    env["HOME"] = tmp_home
    # Toolchain homes are build caches, not credentials — and rustup-managed
    # toolchains are UNUSABLE without them (rustup finds its default toolchain
    # via RUSTUP_HOME; a scrubbed HOME makes every cargo run fail in 0.1s).
    # Carry them from the parent env, defaulting to the real user's homes.
    real_home = os.environ.get("HOME", "")
    for var, sub in (("RUSTUP_HOME", ".rustup"), ("CARGO_HOME", ".cargo")):
        if os.environ.get(var):
            env[var] = os.environ[var]
        elif real_home and os.path.isdir(os.path.join(real_home, sub)):
            env[var] = os.path.join(real_home, sub)
    # scrubbing HOME hides user site-packages; re-expose interpreter paths
    # explicitly so the sandboxed subprocess uses the SAME interpreter env
    import site
    paths = []
    for fn in (site.getsitepackages,):
        try:
            paths.extend(fn())
        except Exception:
            pass
    try:
        paths.append(site.getusersitepackages())
    except Exception:
        pass
    if paths:
        env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


def run_in_dir(workdir: str, argv: list, timeout: int = 120,
               cpu_seconds: int = 60, mem_mb: int = 1024) -> SandboxResult:
    """Run argv inside an existing directory under resource limits."""
    import time
    start = time.monotonic()
    try:
        proc = subprocess.run(
            argv, cwd=workdir, env=clean_env(workdir),
            capture_output=True, text=True, timeout=timeout,
            preexec_fn=_limits(cpu_seconds, mem_mb * 1024 * 1024),
        )
        return SandboxResult(list(argv), proc.returncode, proc.stdout, proc.stderr,
                             False, time.monotonic() - start, workdir)
    except subprocess.TimeoutExpired as exc:
        return SandboxResult(list(argv), None, exc.stdout or "", exc.stderr or "",
                             True, time.monotonic() - start, workdir)


def sandbox_tmpdir(prefix: str = "molt_sandbox_") -> str:
    """Temp dir for sandbox copies. NEVER the default /tmp on hosts where it
    is a small tmpfs: a single cargo target dir overflows a 512M ramdisk and
    the linker dies with a bus error. Base: $MOLT_TMPDIR, else ~/.cache."""
    base = os.environ.get("MOLT_TMPDIR") or os.path.join(
        os.path.expanduser("~"), ".cache", "molt-forge")
    os.makedirs(base, exist_ok=True)
    return tempfile.mkdtemp(prefix=prefix, dir=base)


def run_in_copy(src_dir: str, argv: list, timeout: int = 120,
                cpu_seconds: int = 60, mem_mb: int = 1024) -> SandboxResult:
    """Copy src_dir to a temp dir, run argv there, return result (copy kept for harvest)."""
    tmp = sandbox_tmpdir()
    work = os.path.join(tmp, "work")
    shutil.copytree(src_dir, work)
    return run_in_dir(work, argv, timeout=timeout, cpu_seconds=cpu_seconds, mem_mb=mem_mb)


def test_command(repo_dir: str) -> list:
    """Test command for this repo, from its manifest (see stacks.py).

    Historically this picked a runner from the HOST interpreter, which made
    Forge blind to non-Python repos; it now delegates to stack detection and
    only falls back to the interpreter-based Python runner for unknown trees.
    """
    from . import stacks
    return stacks.test_command(repo_dir)
