"""End-to-end pipeline orchestration, shared by the CLI and the Flask API.

v0.2 (Unkillable Repair build):
- Every stage event is Ed25519-signed by the agent role that performed it
  (identities persist in the job dir; see signing.py).
- Patch strategy is selectable: deterministic mutations (offline fast path)
  or model-authored unified diffs (any stack; agents/patcher_llm.py).
- A differential Skeptic reviews every patch; a Skeptic rejection downgrades
  a would-be "validated" verdict to "proposed-unverified".
- Runs are resumable: state is checkpointed into the job dir after the
  patch stage, so a killed process can be succeeded by a fresh one that
  replays the signed log and finishes the run (resume_pipeline).
"""

from __future__ import annotations

import json
import os
import shutil
import traceback
import uuid

from . import evidence, intake, sandbox
from .agents import analyzer, patcher, patcher_llm, planner, skeptic, verifier
from .graph import Graph
from .kernel import EventLog
from .llm import get_backend
from .signing import IdentityStore

ROLE_FOR_EVENT = {
    "stage": "orchestrator", "intake": "orchestrator", "llm_backend": "planner",
    "analysis": "planner", "patch_attempts": "fixer", "patch": "fixer",
    "patch_failed": "fixer", "verification": "skeptic", "skeptic": "skeptic",
    "baseline": "verifier", "verdict": "verifier", "package": "verifier",
    "issue": "planner", "audit_unactionable": "planner",
}


def _new_job(repo_url, jobs_root, job_id):
    job_id = job_id or uuid.uuid4().hex[:12]
    work = os.path.join(jobs_root, job_id)
    os.makedirs(work, exist_ok=True)
    pkg = os.path.join(work, "package")
    os.makedirs(pkg, exist_ok=True)
    return {"id": job_id, "repo_url": repo_url, "status": "running",
            "verdict": None, "workdir": work, "package_dir": pkg,
            "zip_path": os.path.join(work, f"molt-forge-evidence-{job_id}.zip"),
            "steps": [], "findings": None, "error": None}


def _signer(ids: IdentityStore, event_type: str):
    return ids.get(ROLE_FOR_EVENT.get(event_type, "orchestrator"))


def run_pipeline(repo_url: str, jobs_root: str, job_id: str | None = None,
                 log=lambda *_: None, patch_strategy: str = "auto",
                 stop_after: str | None = None,
                 issue: str | None = None, suspect_hint: str | None = None,
                 backend=None) -> dict:
    job = _new_job(repo_url, jobs_root, job_id)
    work, pkg = job["workdir"], job["package_dir"]
    kernel = EventLog(os.path.join(work, "events.jsonl"))
    ids = IdentityStore(os.path.join(work, "identities.json"))
    graph = Graph()

    def append(event_type, payload):
        return kernel.append(event_type, payload, signer=_signer(ids, event_type))

    def stage(step, desc):
        job["steps"].append({"step": step, "description": desc, "status": "done"})
        append("stage", {"step": step, "description": desc})
        log(f"[stage] {step}: {desc}")

    pipeline_error = None
    baseline = post = None
    patch_info = None
    findings = None
    info = None
    try:
        # --- intake ---
        stage("intake", "Clone repository and pin commit SHA")
        info = intake.intake(repo_url, work)
        append("intake", {"repo_url": repo_url, "pinned_sha": info["pinned_sha"],
                          "languages": info["languages"], "stack": info.get("stack")})
        graph.add_node("repo", "repo", f"repo @ {info['pinned_sha'][:8]}",
                       {"sha": info["pinned_sha"], "url": repo_url})
        for f in info["files"]:
            graph.add_node(f"file:{f}", "module", f)
            graph.add_edge("repo", f"file:{f}", "contains")
        stage("inventory", "Inventory languages and detect test commands")

        # --- plan ---
        job["steps"] = planner.plan(info)
        for s in job["steps"]:
            s["status"] = "done" if s["step"] in ("intake", "inventory") else "pending"

        # --- baseline ---
        stage_mark(job, "baseline")
        if info["has_tests"]:
            baseline = verifier.run_suite(info["repo_dir"])
            evidence.write(os.path.join(pkg, "baseline_test.log"), baseline.transcript())
            append("baseline", {"exit_code": baseline.returncode,
                                "timed_out": baseline.timed_out})
            graph.add_node("run:baseline", "artifact", f"baseline run (exit {baseline.returncode})",
                           {"exit_code": baseline.returncode})
            graph.add_edge("repo", "run:baseline", "executed-in-sandbox")
        else:
            append("baseline", {"skipped": "no tests detected"})

        # --- audit mode: a stated issue on a (possibly passing) suite ---
        if issue:
            verdict = _audit_flow(job, work, pkg, graph, append, info, baseline,
                                  issue, suspect_hint, stop_after, log,
                                  backend or get_backend())
            if job["status"] == "interrupted":
                return job
            _package(job, work, pkg, kernel, ids, graph, verdict, info)
            return job

        # --- analyze ---
        stage_mark(job, "analyze")
        backend = get_backend()
        append("llm_backend", {"backend": backend.name})
        if baseline is not None and not baseline.ok:
            findings = analyzer.analyze(backend, baseline.stdout + baseline.stderr, info["files"])
            job["findings"] = findings
            append("analysis", findings)
            graph.add_node("finding:failure", "finding",
                           f"failing tests: {len(findings['failing_tests'])}", findings)
            graph.add_edge("run:baseline", "finding:failure", "produced")
            if findings.get("suspect_file"):
                graph.add_edge("finding:failure", f"file:{findings['suspect_file']}", "implicates")

            # --- patch ---
            stage_mark(job, "patch")
            if findings.get("suspect_file"):
                strategy = patch_strategy
                if strategy == "auto":
                    strategy = "llm" if hasattr(backend, "generate") else "mutation"
                if strategy == "llm":
                    patch_info = patcher_llm.generate_patch_with_model(
                        info["repo_dir"], findings["suspect_file"],
                        baseline.stdout + baseline.stderr, backend,
                        failing_test_file=findings.get("failing_test_file"), log=log)
                else:
                    patch_info = patcher.generate_patch(
                        info["repo_dir"], findings["suspect_file"],
                        findings.get("failing_test_file"), backend, log=log)
                append("patch_attempts", {"attempts": patch_info["attempts"],
                                          "strategy": patch_info.get("strategy", "mutation")})
                if patch_info.get("patched"):
                    evidence.write(os.path.join(pkg, "patch.diff"), patch_info["diff"])
                    if patch_info.get("regression_test"):
                        evidence.write(os.path.join(pkg, patch_info["regression_test_name"]),
                                       patch_info["regression_test"])
                    append("patch", {"file": patch_info["file"],
                                     "mutation": patch_info["mutation"],
                                     "diff_sha256": evidence.sha256_file(
                                         os.path.join(pkg, "patch.diff"))})
                    graph.add_node("artifact:patch", "artifact", "patch.diff",
                                   {"mutation": patch_info["mutation"]})
                    graph.add_edge("finding:failure", "artifact:patch", "resolved-by")

                    # --- checkpoint: everything a successor needs ---
                    _write_state(work, job, info, findings, patch_info, baseline)
                    graph.save(os.path.join(work, "graph.json"))
                    if stop_after == "patch":
                        append("interrupted", {"reason": "stop_after=patch (kill drill)",
                                               "checkpoint": "state.json"})
                        job["status"] = "interrupted"
                        return job

                    # --- verify ---
                    stage_mark(job, "verify")
                    post = _run_patched(info, patch_info, work)
                    evidence.write(os.path.join(pkg, "patched_test.log"), post.transcript())
                    append("verification", {"exit_code": post.returncode,
                                            "timed_out": post.timed_out})
                    graph.add_node("run:patched", "artifact", f"patched run (exit {post.returncode})",
                                   {"exit_code": post.returncode})
                    graph.add_edge("artifact:patch", "run:patched", "verified-by")
                else:
                    append("patch_failed", {"reason": patch_info.get("reason")})
        elif baseline is not None:
            findings = {"note": "test suite already passes at pinned commit; nothing to patch"}
            job["findings"] = findings
            append("analysis", findings)

        verdict = verifier.decide(baseline, patch_info, post)
        verdict = _skeptic_gate(job, pkg, append, graph, info, patch_info,
                                baseline, post, verdict)
    except Exception:
        pipeline_error = traceback.format_exc()
        kernel.append("pipeline_error", {"traceback": pipeline_error},
                      signer=ids.get("orchestrator"))
        verdict = verifier.decide(baseline, patch_info, post, pipeline_error=pipeline_error)
        job["error"] = pipeline_error

    _package(job, work, pkg, kernel, ids, graph, verdict, info)
    return job


def _audit_flow(job, work, pkg, graph, append, info, baseline, issue,
                suspect_hint, stop_after, log, backend) -> str:
    """Issue-driven repair: the suite may be green; the gate is a regression
    test (inside the model's diff) that FAILS on the unpatched tree and PASSES
    on the patched one — enforced by the Skeptic's test-only differential."""
    append("llm_backend", {"backend": backend.name})
    append("issue", {"issue": issue, "suspect_hint": suspect_hint})
    findings = {"mode": "audit", "issue": issue, "suspect_file": suspect_hint,
                "failing_tests": [], "backend": backend.name}
    job["findings"] = findings
    append("analysis", findings)
    if not suspect_hint or not hasattr(backend, "generate"):
        append("audit_unactionable",
               {"reason": "audit mode needs a suspect hint and a model backend"})
        return verifier.DIAGNOSIS_ONLY
    stage_mark(job, "patch")
    context = ""
    if baseline is not None:
        context = (baseline.stdout + baseline.stderr)[-3000:]
    patch_info = patcher_llm.generate_patch_with_model(
        info["repo_dir"], suspect_hint, context + "\nISSUE: " + issue,
        backend, log=log)
    append("patch_attempts", {"attempts": patch_info["attempts"],
                              "strategy": patch_info.get("strategy", "llm-diff")})
    if not patch_info.get("patched"):
        append("patch_failed", {"reason": patch_info.get("reason")})
        return verifier.DIAGNOSIS_ONLY
    evidence.write(os.path.join(pkg, "patch.diff"), patch_info["diff"])
    if patch_info.get("regression_test"):
        evidence.write(os.path.join(pkg, patch_info["regression_test_name"]),
                       patch_info["regression_test"])
    append("patch", {"file": patch_info["file"], "mutation": patch_info["mutation"],
                     "diff_sha256": evidence.sha256_file(os.path.join(pkg, "patch.diff"))})
    graph.add_node("artifact:patch", "artifact", "patch.diff",
                   {"mutation": patch_info["mutation"]})
    _write_state(work, job, info, findings, patch_info, baseline,
                 extra={"mode": "audit", "issue": issue})
    graph.save(os.path.join(work, "graph.json"))
    if stop_after == "patch":
        append("interrupted", {"reason": "stop_after=patch (kill drill)",
                               "checkpoint": "state.json"})
        job["status"] = "interrupted"
        return verifier.DIAGNOSIS_ONLY  # not reached by caller; status guards it
    stage_mark(job, "verify")
    post = _run_patched(info, patch_info, work)
    evidence.write(os.path.join(pkg, "patched_test.log"), post.transcript())
    append("verification", {"exit_code": post.returncode, "timed_out": post.timed_out})
    verdict = verifier.VALIDATED if post.ok else verifier.PROPOSED_UNVERIFIED
    return _skeptic_gate(job, pkg, append, graph, info, patch_info,
                         baseline, post, verdict)


def _run_patched(info, patch_info, work):
    if patch_info.get("patched_files"):
        return verifier.run_suite_on_patched_files(
            info["repo_dir"], patch_info["patched_files"], os.path.join(work, "patched"))
    return verifier.run_suite_on_patched(
        info["repo_dir"], patch_info["file"], patch_info["patched_source"],
        os.path.join(work, "patched"))


def _skeptic_gate(job, pkg, append, graph, info, patch_info, baseline, post, verdict):
    """Run the differential Skeptic; downgrade a validated verdict it rejects."""
    if not (patch_info and patch_info.get("patched")):
        return verdict
    review = skeptic.review(info["repo_dir"], patch_info, baseline, post)
    job["skeptic"] = review
    evidence.write(os.path.join(pkg, "skeptic.json"), json.dumps(review, indent=2))
    append("skeptic", {"accept": review["accept"], "scope_ok": review["scope_ok"],
                       "changed_files": review["changed_files"],
                       "differential": review["differential"]})
    graph.add_node("agent:skeptic", "agent",
                   f"skeptic: {'accept' if review['accept'] else 'REJECT'}", review)
    graph.add_edge("artifact:patch", "agent:skeptic", "reviewed-by")
    if verdict == verifier.VALIDATED and not review["accept"]:
        append("verdict_downgraded", {"from": verdict, "to": verifier.PROPOSED_UNVERIFIED,
                                      "reason": review["notes"]})
        return verifier.PROPOSED_UNVERIFIED
    return verdict


def _write_state(work, job, info, findings, patch_info, baseline, extra=None):
    state = {
        "job_id": job["id"], "repo_url": job["repo_url"],
        "pinned_sha": info["pinned_sha"] if info else None,
        "repo_dir": info["repo_dir"] if info else None,
        "stack": info.get("stack") if info else None,
        "findings": findings, "patch_info": patch_info,
        "baseline": {"returncode": baseline.returncode if baseline else None,
                     "timed_out": baseline.timed_out if baseline else None},
        "steps": job["steps"],
        **(extra or {}),
    }
    with open(os.path.join(work, "state.json"), "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)


def _package(job, work, pkg, kernel, ids, graph, verdict, info):
    job["verdict"] = verdict

    def append(event_type, payload):
        return kernel.append(event_type, payload, signer=_signer(ids, event_type))

    append("verdict", {"verdict": verdict})
    append("package", {"package_dir": pkg, "zip": job["zip_path"]})
    graph.add_node("verdict", "finding", f"verdict: {verdict}")
    graph.save(os.path.join(pkg, "graph.json"))
    shutil.copy(os.path.join(work, "events.jsonl"), os.path.join(pkg, "events.jsonl"))
    evidence.write(os.path.join(pkg, "findings.json"),
                   json.dumps(job.get("findings"), indent=2))
    pinned_sha = info["pinned_sha"] if info else None
    manifest = evidence.build_manifest(pkg, verdict, {
        "job_id": job["id"], "repo_url": job["repo_url"], "pinned_sha": pinned_sha,
        "agent_pubkeys": {r: ids.get(r).pub_hex for r in
                          ("orchestrator", "planner", "fixer", "skeptic", "verifier")},
    })
    evidence.zip_package(pkg, job["zip_path"])
    job["status"] = "done"
    job["manifest"] = manifest
    return job


def resume_pipeline(jobs_root: str, job_id: str, log=lambda *_: None) -> dict:
    """Finish an interrupted run from its checkpoint + signed log alone.

    The successor process re-opens the SAME event log (chain continues), the
    SAME identities (keys live in the job dir), and the checkpointed state —
    then runs verify, the Skeptic gate, verdict and packaging.
    """
    work = os.path.join(jobs_root, job_id)
    pkg = os.path.join(work, "package")
    with open(os.path.join(work, "state.json"), encoding="utf-8") as fh:
        state = json.load(fh)
    job = _new_job(state["repo_url"], jobs_root, job_id)
    job["findings"] = state.get("findings")
    job["steps"] = state.get("steps") or []
    kernel = EventLog(os.path.join(work, "events.jsonl"))
    ids = IdentityStore(os.path.join(work, "identities.json"))
    graph = Graph()
    if os.path.exists(os.path.join(work, "graph.json")):
        with open(os.path.join(work, "graph.json"), encoding="utf-8") as fh:
            saved = json.load(fh)
        for n in saved.get("nodes", []):
            graph.add_node(n["id"], n["kind"], n["label"], n.get("data"))
        for e in saved.get("edges", []):
            graph.add_edge(e["from"], e["to"], e["relation"])

    def append(event_type, payload):
        return kernel.append(event_type, payload, signer=_signer(ids, event_type))

    # Idempotency: a run that already reached a verdict is complete — a
    # second successor must not re-verify or fork the chain's meaning.
    prior = [e for e in kernel.events if e["type"] == "verdict"]
    if prior:
        job["status"] = "done"
        job["verdict"] = prior[-1]["payload"]["verdict"]
        log(f"[resume] job {job_id} already completed with verdict {job['verdict']}; no-op")
        return job

    append("resumed", {"by": "successor process", "from_checkpoint": "state.json",
                       "events_replayed": len(kernel.events)})
    log(f"[resume] replayed {len(kernel.events)} signed events for job {job_id}")

    info = {"repo_dir": state["repo_dir"], "pinned_sha": state["pinned_sha"],
            "stack": state.get("stack")}
    patch_info = state["patch_info"]
    b = state.get("baseline") or {}
    baseline = sandbox.SandboxResult(["(resumed)"], b.get("returncode"), "", "",
                                     bool(b.get("timed_out")), 0.0)
    post = _run_patched(info, patch_info, work)
    evidence.write(os.path.join(pkg, "patched_test.log"), post.transcript())
    append("verification", {"exit_code": post.returncode, "timed_out": post.timed_out})
    if state.get("mode") == "audit":
        verdict = verifier.VALIDATED if post.ok else verifier.PROPOSED_UNVERIFIED
    else:
        verdict = verifier.decide(baseline, patch_info, post)
    verdict = _skeptic_gate(job, pkg, append, graph, info, patch_info,
                            baseline, post, verdict)
    _package(job, work, pkg, kernel, ids, graph, verdict, info)
    return job


def stage_mark(job, step):
    for s in job["steps"]:
        if s["step"] == step:
            s["status"] = "done"
