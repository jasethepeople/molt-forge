"""Flask API + static judge UI.

  POST /api/jobs               {repo_url} -> {id}
  GET  /api/jobs/<id>          job status, steps, verdict, manifest
  GET  /api/jobs/<id>/graph    investigation graph JSON
  GET  /api/jobs/<id>/package  evidence zip download
  GET  /                       judge UI (web/index.html)
"""

from __future__ import annotations

import json
import os
import threading

from flask import Flask, jsonify, request, send_file, send_from_directory

from .pipeline import run_pipeline

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
JOBS_ROOT = os.environ.get("MOLT_JOBS_DIR", "./molt_jobs")

app = Flask(__name__, static_folder=WEB_DIR, static_url_path="/static")
JOBS: dict[str, dict] = {}


@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/<path:filename>")
def web_files(filename: str):
    return send_from_directory(WEB_DIR, filename)


@app.post("/api/jobs")
def create_job():
    data = request.get_json(force=True, silent=True) or {}
    repo_url = data.get("repo_url")
    if not repo_url:
        return jsonify({"error": "repo_url required"}), 400

    import uuid
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"id": job_id, "repo_url": repo_url, "status": "running", "steps": []}

    def worker():
        JOBS[job_id] = run_pipeline(repo_url, JOBS_ROOT, job_id=job_id)

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"id": job_id}), 202


@app.get("/api/jobs/<job_id>")
def get_job(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    out = {k: v for k, v in job.items() if k != "manifest"}
    if "manifest" in job:
        out["manifest"] = job["manifest"]
    return jsonify(out)


@app.get("/api/jobs/<job_id>/graph")
def get_graph(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    graph_path = os.path.join(job["package_dir"], "graph.json")
    if not os.path.exists(graph_path):
        return jsonify({"nodes": [], "edges": [], "status": job["status"]})
    with open(graph_path, encoding="utf-8") as fh:
        return jsonify(json.load(fh))


@app.get("/api/jobs/<job_id>/package")
def get_package(job_id):
    job = JOBS.get(job_id)
    if not job or not os.path.exists(job.get("zip_path", "")):
        return jsonify({"error": "package not ready", "status": (job or {}).get("status")}), 404
    return send_file(job["zip_path"], as_attachment=True,
                     download_name=os.path.basename(job["zip_path"]))


@app.get("/api/jobs/<job_id>/package-file")
def get_package_file(job_id):
    """Serve one plaintext artifact out of a job's evidence package (e.g.
    patch.diff) for inline display. Only a bare filename directly inside
    package_dir is allowed -- no subdirectories, no path traversal."""
    job = JOBS.get(job_id)
    if not job or "package_dir" not in job:
        return jsonify({"error": "not found"}), 404

    name = request.args.get("f", "")
    # Reject anything that isn't a plain filename: no slashes, no "..".
    if not name or name != os.path.basename(name) or name in (".", ".."):
        return jsonify({"error": "invalid filename"}), 400

    package_dir = os.path.abspath(job["package_dir"])
    full_path = os.path.abspath(os.path.join(package_dir, name))
    if os.path.dirname(full_path) != package_dir or not os.path.isfile(full_path):
        return jsonify({"error": "not found"}), 404

    with open(full_path, encoding="utf-8", errors="replace") as fh:
        return fh.read(), 200, {"Content-Type": "text/plain; charset=utf-8"}


def main():
    os.makedirs(JOBS_ROOT, exist_ok=True)
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")))


if __name__ == "__main__":
    main()
