/* Judge UI: submits jobs, polls status, renders graph/diff/manifest. */

let currentJob = null;
let pollTimer = null;

const $ = (id) => document.getElementById(id);

$("go").addEventListener("click", async () => {
  const repo_url = $("repo-url").value.trim();
  if (!repo_url) return;
  const resp = await fetch("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repo_url }),
  });
  const data = await resp.json();
  currentJob = data.id;
  $("job-panel").hidden = false;
  $("download").hidden = true;
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(poll, 1000);
  poll();
});

async function poll() {
  if (!currentJob) return;
  const job = await (await fetch(`/api/jobs/${currentJob}`)).json();
  renderSteps(job);
  renderVerdict(job);
  if (job.manifest) renderManifest(job.manifest);
  const graph = await (await fetch(`/api/jobs/${currentJob}/graph`)).json();
  if (graph.nodes) Globe.render(graph);
  if (job.status === "done") {
    clearInterval(pollTimer);
    pollTimer = null;
    const pkg = await fetch(`/api/jobs/${currentJob}/package`, { method: "HEAD" });
    if (pkg.ok) {
      $("download").href = `/api/jobs/${currentJob}/package`;
      $("download").hidden = false;
    }
    // show patch if present in manifest
    if (job.manifest && job.manifest.artifacts && job.manifest.artifacts["patch.diff"]) {
      fetchText(`/api/jobs/${currentJob}/package-file?f=patch.diff`);
    }
  }
}

async function fetchText() { /* patch text shown via manifest evidence; kept simple */ }

function renderSteps(job) {
  const ul = $("steps");
  ul.innerHTML = "";
  (job.steps || []).forEach((s) => {
    const li = document.createElement("li");
    li.textContent = `${s.step}: ${s.description}`;
    li.className = s.status === "done" ? "done" : "pending";
    ul.appendChild(li);
  });
}

function renderVerdict(job) {
  const el = $("verdict");
  el.textContent = job.verdict || job.status;
  el.className = "verdict " + (job.verdict || "running");
}

function renderManifest(m) {
  const el = $("manifest");
  let html = `<p><b>verdict:</b> ${m.verdict}<br><b>pinned sha:</b> ${m.pinned_sha || "?"}</p>`;
  html += "<table><tr><th>artifact</th><th>sha256</th></tr>";
  for (const [file, hash] of Object.entries(m.artifacts || {})) {
    html += `<tr><td>${file}</td><td class="hash">${hash.slice(0, 16)}…</td></tr>`;
  }
  el.innerHTML = html + "</table>";
}
