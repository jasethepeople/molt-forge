/* Findings: a plain, readable rendering of the investigation graph.
 * No 3D, no animation -- grouped by kind, click a row for its evidence. */

const Investigation = (() => {
  const KIND_ORDER = ["repo", "module", "finding", "artifact", "agent"];
  const KIND_LABEL = {
    repo: "Repository", module: "Module", finding: "Finding",
    artifact: "Artifact", agent: "Agent decision",
  };

  function render(graph) {
    const el = document.getElementById("findings");
    el.innerHTML = "";
    const nodes = graph.nodes || [];
    if (!nodes.length) {
      el.innerHTML = '<p class="empty">no findings yet</p>';
      return;
    }

    // Any kind order doesn't know about still renders, under its own
    // group, so a future node kind can never silently vanish from the UI.
    const knownKinds = new Set(KIND_ORDER);
    const order = [...KIND_ORDER, ...new Set(nodes.map((n) => n.kind).filter((k) => !knownKinds.has(k)))];

    order.forEach((kind) => {
      const group = nodes.filter((n) => n.kind === kind);
      if (!group.length) return;

      const h3 = document.createElement("h3");
      h3.textContent = KIND_LABEL[kind] || kind;
      el.appendChild(h3);

      const ul = document.createElement("ul");
      ul.className = "findings-group";
      group.forEach((node) => {
        const li = document.createElement("li");
        li.textContent = node.label;
        li.tabIndex = 0;
        li.addEventListener("click", () => showNode(node));
        li.addEventListener("keydown", (e) => {
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); showNode(node); }
        });
        ul.appendChild(li);
      });
      el.appendChild(ul);
    });
  }

  function showNode(node) {
    const el = document.getElementById("node-detail");
    el.textContent = `[${node.kind}] ${node.label}\n` +
      (node.data ? JSON.stringify(node.data, null, 2) : "");
  }

  return { render };
})();
