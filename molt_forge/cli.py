"""CLI: python -m molt_forge.cli <repo_url> — full pipeline, prints verdict + package path.

Kill/resume drill:
  python -m molt_forge.cli <repo> --stop-after patch --job-id drill1   # dies after patching
  python -m molt_forge.cli --resume drill1                             # successor finishes it
"""

from __future__ import annotations

import argparse
import json
import sys

from .pipeline import resume_pipeline, run_pipeline


def main(argv=None):
    parser = argparse.ArgumentParser(prog="molt_forge.cli",
                                     description="MOLT Forge: investigate, patch, verify, package.")
    parser.add_argument("repo_url", nargs="?", help="public git URL or local path to a git repo")
    parser.add_argument("--jobs-dir", default="./molt_jobs",
                        help="directory for job working trees and evidence packages")
    parser.add_argument("--job-id", default=None, help="pin the job id (drills, tests)")
    parser.add_argument("--patch-strategy", choices=["auto", "mutation", "llm"], default="auto")
    parser.add_argument("--issue", default=None,
                        help="audit mode: a stated defect to fix even if the suite passes")
    parser.add_argument("--suspect", default=None,
                        help="audit mode: repo-relative path of the suspect file")
    parser.add_argument("--stop-after", choices=["patch"], default=None,
                        help="halt after this stage, leaving a resumable checkpoint")
    parser.add_argument("--resume", metavar="JOB_ID", default=None,
                        help="resume an interrupted job from its signed log + checkpoint")
    args = parser.parse_args(argv)

    if args.resume:
        job = resume_pipeline(args.jobs_dir, args.resume, log=lambda m: print(m, flush=True))
    else:
        if not args.repo_url:
            parser.error("repo_url is required unless --resume is given")
        job = run_pipeline(args.repo_url, args.jobs_dir, job_id=args.job_id,
                           log=lambda m: print(m, flush=True),
                           patch_strategy=args.patch_strategy, stop_after=args.stop_after,
                           issue=args.issue, suspect_hint=args.suspect)

    print("\n=== MOLT Forge result ===")
    print(f"job id:      {job['id']}")
    print(f"status:      {job['status']}")
    print(f"verdict:     {job['verdict']}")
    if job.get("findings"):
        print(f"findings:    {json.dumps(job['findings'], indent=2)[:800]}")
    if job.get("error"):
        print("pipeline error (documented-failure):")
        print(job["error"])
    print(f"package dir: {job['package_dir']}")
    print(f"package zip: {job['zip_path']}")
    return 0 if job["verdict"] == "validated" else 1


if __name__ == "__main__":
    raise SystemExit(main())
