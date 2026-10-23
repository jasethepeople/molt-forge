/* Judge UI: submits jobs, polls status, renders graph/diff/manifest. */

let currentJob = null;
let pollTimer = null;
let stampedVerdict = null; // guards the stamp-down animation to a single play

const $ = (id) => document.getElementById(id);
const TERMINAL_VERDICTS = new Set([
  "validated", "proposed-unverified", "diagnosis-only", "documented-failure",
]);

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
  stampedVerdict = null;

  $("job-panel").hidden = false;
  $("download").hidden = true;
  $("verdict").className = "verdict running";
  $("verdict").textContent = "pending";
  $("case-id").hidden = false;
  $("case-id-value").textContent = currentJob;

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
  if (graph.nodes) Investigation.render(graph);
  if (job.status === "done") {
    clearInterval(pollTimer);
    pollTimer = null;
    const pkg = await fetch(`/api/jobs/${currentJob}/package`, { method: "HEAD" });
    if (pkg.ok) {
      $("download").href = `/api/jobs/${currentJob}/package`;
      $("download").hidden = false;
    }
  }
}

function renderSteps(job) {
  const ol = $("steps");
  ol.innerHTML = "";
  (job.steps || []).forEach((s) => {
    const li = document.createElement("li");
    li.textContent = `${s.description}`;
    li.className = s.status === "done" ? "done" : "pending";
    ol.appendChild(li);
  });
}

function renderVerdict(job) {
  const el = $("verdict");
  const v = job.verdict || null;

  if (v && TERMINAL_VERDICTS.has(v)) {
    el.textContent = v;
    el.className = "verdict " + v;
    if (stampedVerdict !== v) {
      // play the stamp-down animation exactly once per resolved verdict
      el.classList.remove("stamped");
      void el.offsetWidth; // restart the animation
      el.classList.add("stamped");
      stampedVerdict = v;
    }
  } else {
    el.textContent = job.status || "pending";
    el.className = "verdict running";
  }
}

function renderManifest(m) {
  const el = $("manifest");
  let html = `<p><b>verdict:</b> ${m.verdict}<br><b>pinned sha:</b> ${m.pinned_sha || "?"}</p>`;
  html += "<table><tr><th>artifact</th><th>sha256</th></tr>";
  for (const [file, hash] of Object.entries(m.artifacts || {})) {
    html += `<tr><td>${file}</td><td class="hash">${hash.slice(0, 16)}…</td></tr>`;
  }
  el.innerHTML = html + "</table>";

  if (m.artifacts && m.artifacts["patch.diff"]) {
    fetch(`/api/jobs/${currentJob}/package-file?f=patch.diff`)
      .then((r) => (r.ok ? r.text() : null))
      .then((text) => { if (text) $("diff").textContent = text; })
      .catch(() => {});
  }
}
