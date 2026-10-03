// The studio's 3D view: a second renderer of the page's state. The page owns the plan, the selection and the replay position; this draws
// them. Loaded on demand (the first time 3D is opened) with three.js vendored beside it (vendor/three, MIT).
//
// Scene frame (model_place.py): x = board x, y = up, z = board y (down the page), millimetres, the board body from 0 to its thickness.
// The plan document carries each part's models with a matrix from the model frame to this frame; the page's job here is to apply them, never
// to work out a pose. A model is read once (`.pmm`, model_mesh.py) and drawn with one InstancedMesh per (model, material); the instances
// of a group are ordered by the step that placed them, so showing the first k steps of the replay is a count.
import * as THREE from "three";
import { OrbitControls } from "./OrbitControls.js";

const css = (n, d) => (getComputedStyle(document.documentElement).getPropertyValue(n) || "").trim() || d;
const dark = () => matchMedia("(prefers-color-scheme: dark)").matches && document.documentElement.dataset.theme !== "light" || document.documentElement.dataset.theme === "dark";

// ---------------------------------------------------------------- the mesh file
export function parsePmm(buf) {
  const dv = new DataView(buf);
  if (buf.byteLength < 12 || String.fromCharCode(...new Uint8Array(buf, 0, 6)) !== "PMMESH") throw new Error("not a placemat mesh");
  const hl = dv.getUint32(8, true);
  const header = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 12, hl)));
  let at = 12 + hl;
  const mats = [];
  for (const m of header.materials) {
    const pos = new Float32Array(buf, at, 3 * m.nv); at += 12 * m.nv;
    const nor = new Float32Array(buf, at, 3 * m.nv); at += 12 * m.nv;
    const idx = m.index_bytes === 2 ? new Uint16Array(buf, at, m.ni) : new Uint32Array(buf, at, m.ni);
    at += m.index_bytes * m.ni; at += (4 - at % 4) % 4;
    mats.push({colour: m.colour, opacity: m.opacity, pos, nor, idx});
  }
  return {header, mats};
}

const upper = (arr, k) => { let lo = 0, hi = arr.length; while (lo < hi) { const mid = (lo + hi) >> 1; if (arr[mid] < k) lo = mid + 1; else hi = mid; } return lo; };   // how many of a sorted array are below k

function hatch(color) {
  const c = document.createElement("canvas"); c.width = c.height = 64;
  const g = c.getContext("2d");
  g.clearRect(0, 0, 64, 64); g.strokeStyle = color; g.lineWidth = 5;
  for (let i = -64; i < 128; i += 16) { g.beginPath(); g.moveTo(i, 64); g.lineTo(i + 64, 0); g.stroke(); }
  const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(0.5, 0.5); t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

function labelTexture(text, color) {
  const c = document.createElement("canvas"); c.width = 256; c.height = 64;
  const g = c.getContext("2d");
  g.fillStyle = color; g.font = "bold 22px system-ui, sans-serif"; g.textAlign = "center"; g.textBaseline = "middle";
  g.fillText(text.length > 30 ? text.slice(0, 29) + "..." : text, 128, 32);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

const planeOf = T => [T - 0.005, -0.085];

export async function mount(host) {
  const parent = host.parent;
  const canvas = document.createElement("canvas");
  canvas.id = "board3d"; canvas.style.cssText = "position:absolute;inset:0;width:100%;height:100%;touch-action:none;display:block";
  parent.insertBefore(canvas, parent.firstChild);
  const renderer = new THREE.WebGLRenderer({canvas, antialias: true, powerPreference: "high-performance"});
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(30, 1, 0.5, 4000);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x556070, 1.25));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6); sun.position.set(60, 120, 40); scene.add(sun);
  const under = new THREE.DirectionalLight(0xffffff, 1.1); under.position.set(-50, -120, -30); scene.add(under);        // the back is lit too
  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = false; controls.screenSpacePanning = true; controls.maxPolarAngle = Math.PI; controls.minDistance = 2;
  controls.touches = {ONE: THREE.TOUCH.ROTATE, TWO: THREE.TOUCH.DOLLY_PAN};

  const state = {
    sig: "", T: 1.6, extent: [0, 0, 100, 60], assets: new Map(), loading: new Set(), groups: [], plates: [], body: null, root: new THREE.Group(),
    selKey: null, selObjs: [], animations: [], seen: new Set(), visible: true, dirty: true, k: null, theme: null, order: [], keyN: new Map(), stats: {},
    dim: false, over: false, hover: null,
  };
  scene.add(state.root);
  const request = () => { state.dirty = true; if (!state.raf && state.visible) state.raf = requestAnimationFrame(frame); };
  controls.addEventListener("change", request);

  // ---- theme
  function theme() {
    const d = dark();
    const t = {
      bg: css("--b3-bg", d ? "#1b2027" : "#e6e9ed"), body: css("--b3-body", d ? "#1d5a3c" : "#2f7a52"), plate: css("--b3-plate", d ? "#8f8bf0" : "#5b54c9"),
      text: css("--b3-text", d ? "#d8dce2" : "#1b1f24"), edge: css("--b3-edge", d ? "#7fd1a0" : "#103a26"), accent: css("--accent", "#2563eb"),
    };
    state.theme = t;
    renderer.setClearColor(new THREE.Color(t.bg), 1);
    if (state.body) state.body.material.color.set(t.body);
    for (const p of state.plates) p.recolor(t);
    request();
  }
  const mq = matchMedia("(prefers-color-scheme: dark)");
  mq.addEventListener && mq.addEventListener("change", theme);

  // ---- the board body: the outline extruded to the thickness, cutouts and drills as holes
  function ring(poly) { return poly.map(p => new THREE.Vector2(p[0], -p[1])); }
  function area(l) { const xs = l.map(p => p[0]), ys = l.map(p => p[1]); return (Math.max(...xs) - Math.min(...xs)) * (Math.max(...ys) - Math.min(...ys)); }
  function circle(cx, cy, r, n = 14) { const out = []; for (let i = 0; i < n; i++) { const a = 2 * Math.PI * i / n; out.push(new THREE.Vector2(cx + r * Math.cos(a), -(cy + r * Math.sin(a)))); } return out; }
  function buildBody(plan) {
    if (state.body) { state.root.remove(state.body); state.body.geometry.dispose(); state.body = null; }
    const loops = (plan.board && plan.board.loops || []).filter(l => l.length >= 3);
    const T = state.T;
    let outer = null;
    if (loops.length) outer = loops.reduce((a, b) => area(b) > area(a) ? b : a);
    const ext = state.extent;
    const shape = new THREE.Shape(outer ? ring(outer) : [new THREE.Vector2(ext[0], -ext[1]), new THREE.Vector2(ext[2], -ext[1]), new THREE.Vector2(ext[2], -ext[3]), new THREE.Vector2(ext[0], -ext[3])]);
    for (const l of loops) if (l !== outer) shape.holes.push(new THREE.Path(ring(l)));
    const drills = [];
    for (const c of plan.copper || []) if (c.t === "via" && c.drill > 0) drills.push([c.at[0], c.at[1], c.drill / 2]);
    for (const it of plan.items || []) for (const m of it.members || []) for (const s of m.shapes || []) if ((s.kind === "hole" || s.kind === "npth") && s.poly && s.poly.length >= 3) {
      const xs = s.poly.map(p => p[0]), ys = s.poly.map(p => p[1]);
      drills.push([(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2, (Math.max(...xs) - Math.min(...xs)) / 2]);
    }
    for (const [x, y, r] of drills) if (r > 0.05 && (!outer || ptIn([x, y], outer))) shape.holes.push(new THREE.Path(circle(x, y, r)));
    const geo = new THREE.ExtrudeGeometry(shape, {depth: T, bevelEnabled: false, curveSegments: 6});
    geo.rotateX(-Math.PI / 2);                    // shape (x, -y, depth) to scene (x, depth up, y)
    const mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({color: state.theme.body, roughness: 0.75, metalness: 0.0, side: THREE.DoubleSide}));
    mesh.userData.body = true;
    state.body = mesh; state.root.add(mesh);
  }
  function ptIn(p, loop) { let h = false; for (let i = 0, j = loop.length - 1; i < loop.length; j = i++) { const a = loop[i], b = loop[j]; if ((a[1] > p[1]) !== (b[1] > p[1]) && p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1]) + a[0]) h = !h; } return h; }

  // ---- assets
  function assetOf(id) {
    const a = state.assets.get(id);
    if (a) return a;
    if (state.loading.has(id)) return null;
    const row = (host.models() || {})[id];
    if (!row || row.state !== "ok") return null;
    state.loading.add(id);
    host.fetchMesh(id).then(buf => {
      const p = parsePmm(buf);
      state.assets.set(id, {id, header: p.header, mats: p.mats.map(m => {
        const g = new THREE.BufferGeometry();
        g.setAttribute("position", new THREE.BufferAttribute(m.pos, 3));
        g.setAttribute("normal", new THREE.BufferAttribute(m.nor, 3));
        g.setIndex(new THREE.BufferAttribute(m.idx, 1));
        const col = new THREE.Color().setRGB(m.colour[0] / 255, m.colour[1] / 255, m.colour[2] / 255, THREE.SRGBColorSpace);
        const mk = (o) => new THREE.MeshStandardMaterial({color: col, roughness: 0.55, metalness: 0.15, side: THREE.DoubleSide, transparent: m.opacity < 1 || o < 1, opacity: m.opacity * o});
        return {geometry: g, mat: mk(1), dim: mk(0.28), tris: m.idx.length / 3};
      })});
    }).catch(() => { state.assets.set(id, {id, failed: true, mats: []}); }).finally(() => { state.loading.delete(id); state.sig = ""; host.changed(); });
    return null;
  }

  // ---- parts: instanced models, plates for the rest
  function clearParts() {
    for (const g of state.groups) { state.root.remove(g.mesh); g.mesh.dispose(); }
    for (const p of state.plates) { state.root.remove(p.object); p.dispose(); }
    clearSel();
    state.groups = []; state.plates = [];
  }
  function polyOf(member) { const s = (member.shapes || []).find(x => x.kind === "courtyard"); return s ? s : null; }
  function makePlate(item, member, why, n, loading) {
    const cy = polyOf(member);
    const T = state.T, th = host.settings().plate_mm || 0.1;
    const back = cy ? (cy.faces || ["front"])[0] === "back" : item.face === "back";
    let pts = cy ? cy.poly : null;
    if (!pts || pts.length < 3) {                                           // no courtyard either: a marker at the part
      const at = item.at || [0, 0];
      pts = [[at[0] - 0.6, at[1] - 0.6], [at[0] + 0.6, at[1] - 0.6], [at[0] + 0.6, at[1] + 0.6], [at[0] - 0.6, at[1] + 0.6]];
    }
    const geo = new THREE.ExtrudeGeometry(new THREE.Shape(ring(pts)), {depth: th, bevelEnabled: false});
    geo.rotateX(-Math.PI / 2);
    const t = state.theme;
    const tex = hatch(t.plate);
    const top = new THREE.MeshBasicMaterial({map: tex, transparent: true, opacity: 0.85, side: THREE.DoubleSide, depthWrite: false});
    const side = new THREE.MeshBasicMaterial({color: new THREE.Color(t.plate), transparent: true, opacity: 0.55});
    const mesh = new THREE.Mesh(geo, [top, side]);
    const obj = new THREE.Group();
    obj.add(mesh);
    obj.position.y = back ? -th : T;
    const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
    const w = Math.max(...xs) - Math.min(...xs), h = Math.max(...ys) - Math.min(...ys);
    let label = null;
    if (w >= 4 && h >= 1.5) {
      label = new THREE.Mesh(new THREE.PlaneGeometry(Math.min(w, h * 4) * 0.9, Math.min(w, h * 4) * 0.9 / 4), new THREE.MeshBasicMaterial({map: labelTexture(loading ? "loading" : "no model: " + why, t.text), transparent: true, depthWrite: false}));
      label.rotation.x = -Math.PI / 2; label.position.set((Math.min(...xs) + Math.max(...xs)) / 2, th + 0.02, (Math.min(...ys) + Math.max(...ys)) / 2);
      obj.add(label);
    }
    const plate = {n, key: item.key, ref: member.ref, why, loading, object: obj, mesh, tex, label, sel: false,
      recolor(tt) { top.map = hatch(tt.plate); top.needsUpdate = true; side.color.set(tt.plate); },
      dispose() { geo.dispose(); tex.dispose(); top.dispose(); side.dispose(); if (label) { label.geometry.dispose(); label.material.map.dispose(); label.material.dispose(); } }};
    mesh.userData.plate = plate;
    state.root.add(obj);
    return plate;
  }

  function rebuild(plan, order) {
    clearParts();
    const T = state.T;
    const nOf = new Map();
    for (const s of order) if (s.type === "place") nOf.set(s.item, s.n);
    state.keyN = nOf;
    const byGroup = new Map();
    let dueLoading = false;
    for (const it of plan.items || []) {
      const n = nOf.get(it.key);
      if (n == null) continue;
      for (const m of it.members || []) {
        const ms = m.models || [];
        let drawn = 0, why = "";
        for (const e of ms) {
          if (e.state === "ok" || e.state === "vrml") {
            const a = e.id ? assetOf(e.id) : null;
            if (a && !a.failed && e.matrix) {
              a.mats.forEach((mat, i) => {
                const gk = e.id + ":" + i;
                let g = byGroup.get(gk);
                if (!g) { g = {key: gk, asset: a, i, mat, entries: []}; byGroup.set(gk, g); }
                g.entries.push({n, key: it.key, ref: m.ref, matrix: e.matrix});
              });
              drawn++;
            } else if (a && a.failed) why = why || "model could not be read";
            else {
              const row = (host.models() || {})[e.id];
              if (row && row.state === "failed") why = row.message || "conversion failed";
              else { why = "loading"; dueLoading = true; }
            }
          } else if (e.state === "hidden") why = why || "model hidden";
          else why = why || e.why || (e.state === "missing" ? "model not found" : "no model declared");
        }
        if (!ms.length) why = "no model declared";
        if (!drawn) state.plates.push(makePlate(it, m, why || "no model declared", n, why === "loading"));
      }
    }
    for (const g of byGroup.values()) {
      g.entries.sort((a, b) => a.n - b.n);
      g.ns = g.entries.map(e => e.n);
      const mesh = new THREE.InstancedMesh(g.mat.geometry, g.mat.mat, g.entries.length);
      const mtx = new THREE.Matrix4();
      g.entries.forEach((e, i) => { mtx.fromArray(e.matrix); mesh.setMatrixAt(i, mtx); });
      mesh.instanceMatrix.needsUpdate = true;
      mesh.userData.group = g; g.mesh = mesh; mesh.frustumCulled = false;
      mesh.computeBoundingSphere();
      state.root.add(mesh);
      state.groups.push(g);
    }
    state.tris = state.groups.reduce((s, g) => s + g.entries.length * g.mat.tris, 0);
    state.over = state.tris > (host.settings().max_tris || 4000000);
    state.loadingParts = dueLoading;
  }

  // the first k steps are a count of each group's instances
  function showSteps(k) {
    state.k = k;
    const lim = k == null ? Infinity : k;
    for (const g of state.groups) { g.mesh.count = state.over ? 0 : upper(g.ns, lim); }
    for (const p of state.plates) p.object.visible = p.n < lim;
    request();
  }

  // ---- selection: the selected part is drawn whole, the rest faded
  function clearSel() {
    for (const o of state.selObjs) { state.root.remove(o); if (o.dispose) o.dispose(); if (o.geometry && o.userData.own) o.geometry.dispose(); }
    state.selObjs = [];
  }
  function applySel() {
    clearSel();
    const key = state.selKey;
    for (const g of state.groups) g.mesh.material = key ? g.mat.dim : g.mat.mat;
    for (const p of state.plates) p.mesh.material[1].opacity = key && p.key !== key ? 0.2 : 0.55;
    if (!key) { request(); return; }
    for (const g of state.groups) {
      const es = g.entries.filter(e => e.key === key && e.n < (state.k == null ? Infinity : state.k));
      if (!es.length) continue;
      const m = new THREE.InstancedMesh(g.mat.geometry, g.mat.mat, es.length);
      const mtx = new THREE.Matrix4();
      es.forEach((e, i) => { mtx.fromArray(e.matrix); m.setMatrixAt(i, mtx); });
      m.instanceMatrix.needsUpdate = true; m.frustumCulled = false;
      state.root.add(m); state.selObjs.push(m);
    }
    const box = selectionBox(key);
    if (box) {
      const geo = new THREE.EdgesGeometry(new THREE.BoxGeometry(box.size.x, box.size.y, box.size.z));
      const line = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({color: new THREE.Color(state.theme.accent)}));
      line.position.copy(box.center); line.userData.own = true;
      state.root.add(line); state.selObjs.push(line);
    }
    request();
  }
  function selectionBox(key) {
    const b = new THREE.Box3(), v = new THREE.Vector3(), mtx = new THREE.Matrix4();
    for (const g of state.groups) for (const e of g.entries) if (e.key === key) {
      const h = g.asset.header.bbox; mtx.fromArray(e.matrix);
      for (const x of [h[0], h[3]]) for (const y of [h[1], h[4]]) for (const z of [h[2], h[5]]) b.expandByPoint(v.set(x, y, z).applyMatrix4(mtx));
    }
    for (const p of state.plates) if (p.key === key) b.expandByObject(p.object);
    if (b.isEmpty()) return null;
    const size = b.getSize(new THREE.Vector3()).addScalar(0.1), center = b.getCenter(new THREE.Vector3());
    return {size, center};
  }

  // ---- the camera
  function bounds() {
    const e = state.extent;
    return {cx: (e[0] + e[2]) / 2, cz: (e[1] + e[3]) / 2, w: Math.max(1, e[2] - e[0]), h: Math.max(1, e[3] - e[1])};
  }
  function setView(name) {
    const b = bounds(), T = state.T;
    const span = Math.max(b.w, b.h * (camera.aspect < 1 ? 1 : 1));
    const fov = THREE.MathUtils.degToRad(camera.fov);
    const need = Math.max(b.h / 2, b.w / 2 / Math.max(camera.aspect, 0.2)) / Math.tan(fov / 2) * 1.12 + 8;
    const target = new THREE.Vector3(b.cx, T / 2, b.cz);
    controls.target.copy(target);
    let dir;
    if (name === "top") dir = new THREE.Vector3(0, Math.cos(1e-4), Math.sin(1e-4));
    else if (name === "bottom") dir = new THREE.Vector3(0, -Math.cos(1e-4), -Math.sin(1e-4));
    else dir = new THREE.Vector3(0.55, 0.75, 0.9).normalize();
    camera.position.copy(target).add(dir.multiplyScalar(need * (name === "iso" ? 1.05 : 1)));
    camera.near = Math.max(0.2, need / 200); camera.far = need * 10 + 400; camera.updateProjectionMatrix();
    controls.update(); request();
  }
  function fit() { setView(state.viewName || "iso"); }

  // ---- picking
  const ray = new THREE.Raycaster();
  function pick(ev) {
    const r = canvas.getBoundingClientRect();
    ray.setFromCamera(new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1), camera);
    const objs = [];
    for (const g of state.groups) if (g.mesh.count) objs.push(g.mesh);
    for (const p of state.plates) if (p.object.visible) objs.push(p.mesh);
    const hits = ray.intersectObjects(objs, false);
    for (const h of hits) {
      if (h.object.userData.group) { const e = h.object.userData.group.entries[h.instanceId]; if (e) return {key: e.key, ref: e.ref}; }
      else if (h.object.userData.plate) return {key: h.object.userData.plate.key, ref: h.object.userData.plate.ref};
    }
    return null;
  }
  let down = null;
  canvas.addEventListener("pointerdown", e => { down = {x: e.clientX, y: e.clientY, t: performance.now()}; });
  canvas.addEventListener("pointerup", e => {
    if (!down) return;
    const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y), dt = performance.now() - down.t;
    down = null;
    if (moved > 5 || dt > 500 || e.button > 0) return;
    const hit = pick(e);
    host.select(hit ? hit.key : null, hit ? hit.ref : null);
  });
  canvas.addEventListener("dblclick", () => fit());
  let lastTap = 0;
  canvas.addEventListener("touchend", e => { const now = performance.now(); if (now - lastTap < 300) fit(); lastTap = now; });
  let hoverAt = 0;
  canvas.addEventListener("pointermove", e => {
    if (e.buttons || e.pointerType === "touch") return;
    const now = performance.now();
    if (now - hoverAt < 70) return;
    hoverAt = now;
    const h = pick(e);
    host.hover(h ? h.key : null, h ? h.ref : null, e.clientX, e.clientY);
  });
  canvas.addEventListener("pointerleave", () => host.hover(null, null, 0, 0));

  // ---- the frame
  function resize() {
    const w = parent.clientWidth, h = parent.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h; camera.updateProjectionMatrix(); request();
  }
  new ResizeObserver(resize).observe(parent);
  function frame(now) {
    state.raf = 0;
    if (!state.visible) return;
    let animating = false;
    if (state.animations.length) {
      const ms = host.settings().appear_ms || 0, mtx = new THREE.Matrix4(), lift = new THREE.Matrix4();
      state.animations = state.animations.filter(a => {
        const t = ms ? Math.min(1, (now - a.t0) / ms) : 1, e = 1 - Math.pow(1 - t, 3);
        mtx.fromArray(a.entry.matrix);
        lift.makeTranslation(0, 4 * (1 - e), 0);
        a.group.mesh.setMatrixAt(a.i, lift.multiply(mtx));
        a.group.mesh.instanceMatrix.needsUpdate = true;
        return t < 1;
      });
      animating = state.animations.length > 0;
    }
    if (state.loadingParts) {                                         // plates of models still converting pulse faintly
      const o = 0.5 + 0.25 * Math.sin(now / 350);
      for (const p of state.plates) if (p.loading) p.mesh.material[0].opacity = o;
      animating = true;
    }
    renderer.render(scene, camera);
    const info = renderer.info.render;
    state.stats = {calls: info.calls, triangles: info.triangles, groups: state.groups.length, plates: state.plates.length, instances: state.groups.reduce((s, g) => s + g.mesh.count, 0), over: state.over};
    state.dirty = false;
    if (animating) request();
  }

  // ---- the page's calls
  const api = {
    // Bring the scene to the page's state: the plan, the replay position (null: all), whether a new part should drop in.
    sync(opts = {}) {
      const plan = host.getPlan();
      if (!plan) return;
      const order = host.order();
      state.T = plan.stackup ? plan.stackup.thickness : 1.6;
      const e = plan.board && plan.board.extent;
      if (e) state.extent = e;
      const sig = (plan.items || []).map(i => i.key + ":" + (i.at || "") + ":" + i.rotation + ":" + i.face + ":" + ((i.members || []).map(m => (m.models || []).map(x => x.id + x.state).join(",")).join(";"))).join("|") +
        "#" + order.length + "#" + Object.values(host.models() || {}).map(v => v.state[0]).join("") + "#" + state.assets.size + "#" + ((plan.board && plan.board.loops || []).length) + "#" + (plan.copper || []).filter(c => c.t === "via").length;
      let fresh = [];
      if (sig !== state.sig) {
        const first = !state.sig;
        const before = new Set(state.seen);
        if (!state.body || (state.bodySig !== boardSig(plan))) { buildBody(plan); state.bodySig = boardSig(plan); }
        rebuild(plan, order);
        state.sig = sig;
        state.seen = new Set((plan.items || []).map(i => i.key));
        fresh = first || !opts.animate ? [] : [...state.seen].filter(k => !before.has(k));
        if (first) { setView(state.viewName || "iso"); }
      }
      const prevK = state.k;
      showSteps(opts.k == null ? null : opts.k);
      if (opts.play && opts.k != null && prevK != null && opts.k > prevK && opts.k - prevK <= 3 && (host.settings().appear_ms || 0) > 0) {
        const now = performance.now();                 // Play: the part the step brings in drops in
        for (const g of state.groups) g.entries.forEach((en, i) => { if (en.n >= prevK && en.n < opts.k) state.animations.push({group: g, i, entry: en, t0: now}); });
      }
      if (fresh.length && (host.settings().appear_ms || 0) > 0) {
        const now = performance.now();
        for (const g of state.groups) g.entries.forEach((en, i) => { if (fresh.includes(en.key)) state.animations.push({group: g, i, entry: en, t0: now}); });
      }
      if (state.selKey !== (host.selected() || null)) { state.selKey = host.selected() || null; applySel(); }
      else if (sig !== state.lastSelSig) applySel();
      state.lastSelSig = sig;
      request();
    },
    select(key) { if (state.selKey !== (key || null)) { state.selKey = key || null; applySel(); } },
    setView(name) { state.viewName = name; setView(name); },
    fit, resize, theme,
    show(on) { state.visible = on; canvas.style.display = on ? "block" : "none"; if (on) { resize(); request(); } },
    dim(on) { state.dim = on; for (const g of state.groups) g.mesh.material = on ? g.mat.dim : g.mat.mat; request(); },
    stats() { return Object.assign({}, state.stats, {tris: state.tris, loading: state.loading.size}); },
    // Bring a part's box into view (the card's "zoom"): the camera keeps its direction.
    zoomTo(key) {
      const box = selectionBox(key);
      if (!box) return;
      const dir = camera.position.clone().sub(controls.target).normalize();
      const r = Math.max(box.size.x, box.size.y, box.size.z) * 1.2 + 4;
      controls.target.copy(box.center); camera.position.copy(box.center).add(dir.multiplyScalar(r * 2.2)); controls.update(); request();
    },
    renderNow() { frame(performance.now()); },
    canvas, three: THREE, state, camera, controls,
    dispose() { renderer.dispose(); canvas.remove(); },
  };
  const boardSig = plan => JSON.stringify([plan.board && plan.board.loops, state.T]) + (plan.copper || []).filter(c => c.t === "via").length;
  theme();
  resize();
  return api;
}
