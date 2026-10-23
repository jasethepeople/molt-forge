/* Investigation map: nodes on a sphere.
 * Uses vendored three.js when available; otherwise falls back to a
 * dependency-free canvas 3D projection so the UI works fully offline. */

const Globe = (() => {
  const COLORS = { repo: 0x8fa8c8, module: 0x6b7f6b, finding: 0xc8a05a, artifact: 0x9a7fb8 };
  let graph = null;
  let canvas, ctx, angle = 0;
  let three = null; // {scene, camera, renderer, points, raycaster}

  function layout(nodes) {
    // Fibonacci sphere layout
    const pts = [];
    const n = Math.max(nodes.length, 1);
    nodes.forEach((node, i) => {
      const y = 1 - (i / n) * 2;
      const r = Math.sqrt(Math.max(0, 1 - y * y));
      const theta = i * 2.399963;
      pts.push({ node, x: Math.cos(theta) * r, y, z: Math.sin(theta) * r });
    });
    return pts;
  }

  function initThree() {
    canvas = document.getElementById("globe");
    const w = canvas.clientWidth || 600, h = canvas.clientHeight || 480;
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(55, w / h, 0.1, 100);
    camera.position.z = 3;
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    renderer.setSize(w, h, false);
    const group = new THREE.Group();
    scene.add(group);
    scene.add(new THREE.AmbientLight(0xffffff, 1.2));
    three = { scene, camera, renderer, group };
    canvas.addEventListener("click", onThreeClick);
    animateThree();
  }

  function renderThree(pts) {
    three.group.clear();
    const sphere = new THREE.Mesh(
      new THREE.SphereGeometry(0.98, 32, 32),
      new THREE.MeshBasicMaterial({ color: 0x2a3140, wireframe: true, transparent: true, opacity: 0.35 }));
    three.group.add(sphere);
    pts.forEach((p) => {
      const m = new THREE.Mesh(
        new THREE.SphereGeometry(0.045, 12, 12),
        new THREE.MeshBasicMaterial({ color: COLORS[p.node.kind] || 0x888888 }));
      m.position.set(p.x, p.y, p.z);
      m.userData.node = p.node;
      three.group.add(m);
    });
  }

  function animateThree() {
    requestAnimationFrame(animateThree);
    if (three) { three.group.rotation.y += 0.004; three.renderer.render(three.scene, three.camera); }
  }

  function onThreeClick(e) {
    const rect = canvas.getBoundingClientRect();
    const mouse = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1);
    const ray = new THREE.Raycaster();
    ray.setFromCamera(mouse, three.camera);
    const hits = ray.intersectObjects(three.group.children.filter((c) => c.userData.node));
    if (hits.length) showNode(hits[0].object.userData.node);
  }

  // --- canvas fallback (no three.js) ---
  function initCanvas() {
    canvas = document.getElementById("globe");
    ctx = canvas.getContext("2d");
    canvas.width = canvas.clientWidth || 600;
    canvas.height = canvas.clientHeight || 480;
    canvas.addEventListener("click", onCanvasClick);
    animateCanvas();
  }

  let canvasPts = [];
  function project(p) {
    const ca = Math.cos(angle), sa = Math.sin(angle);
    const x = p.x * ca - p.z * sa, z = p.x * sa + p.z * ca;
    const scale = canvas.height * 0.4;
    return { sx: canvas.width / 2 + x * scale, sy: canvas.height / 2 - p.y * scale, z, node: p.node };
  }

  function animateCanvas() {
    requestAnimationFrame(animateCanvas);
    if (!ctx || !canvasPts.length) return;
    angle += 0.004;
    ctx.fillStyle = "#14171d";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = "#2a3140";
    ctx.beginPath();
    ctx.arc(canvas.width / 2, canvas.height / 2, canvas.height * 0.4, 0, 7);
    ctx.stroke();
    canvasPts.map(project).sort((a, b) => a.z - b.z).forEach((q) => {
      const c = "#" + (COLORS[q.node.kind] || 0x888888).toString(16).padStart(6, "0");
      ctx.fillStyle = c;
      ctx.globalAlpha = 0.4 + 0.6 * (q.z + 1) / 2;
      ctx.beginPath();
      ctx.arc(q.sx, q.sy, 5, 0, 7);
      ctx.fill();
      ctx.globalAlpha = 1;
      q.drawn = true;
    });
    canvas._projected = canvasPts.map(project);
  }

  function onCanvasClick(e) {
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    for (const q of (canvas._projected || [])) {
      if ((q.sx - mx) ** 2 + (q.sy - my) ** 2 < 100) { showNode(q.node); return; }
    }
  }

  function showNode(node) {
    const el = document.getElementById("node-detail");
    el.textContent = `[${node.kind}] ${node.label}\n` +
      (node.data ? JSON.stringify(node.data, null, 2) : "");
  }

  function render(g) {
    graph = g;
    const pts = layout(g.nodes || []);
    if (window.THREE) {
      if (!three) initThree();
      renderThree(pts);
    } else {
      if (!ctx) initCanvas();
      canvasPts = pts;
    }
  }

  return { render };
})();
