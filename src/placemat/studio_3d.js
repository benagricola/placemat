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

import { parsePmm, upper, partSteps, plateOutline, layerStack, drawHeight, spreadHeight, spreadLift, bodyLook as lookOf, viaSpan, trackPolys, visibleRanges, copperShown, findingLayer, pickMarks } from "./viewer_core.js";
export { parsePmm };

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
    copper: [], vias: [], stack: null, bodyMode: "solid", spreadK: 0, spreadFrom: 0, spreadTo: 0, spreadT0: 0, sheets: [],
  };
  scene.add(state.root);
  const request = () => { state.dirty = true; if (!state.raf && state.visible) state.raf = requestAnimationFrame(frame); };
  controls.addEventListener("change", request);
  controls.addEventListener("start", () => { state.userMoved = true; });             // the viewer took the camera: it is not refitted under them

  // ---- theme
  function theme() {
    const d = dark();
    const t = {
      bg: css("--b3-bg", d ? "#1b2027" : "#e6e9ed"), body: css("--b3-body", d ? "#1d5a3c" : "#2f7a52"), plate: css("--b3-plate", d ? "#8f8bf0" : "#5b54c9"),
      grid: css("--b3-grid", d ? "#3a424d" : "#b9c0c9"), text: css("--b3-text", d ? "#d8dce2" : "#1b1f24"), edge: css("--b3-edge", d ? "#7fd1a0" : "#103a26"), accent: css("--accent", "#2563eb"),
    };
    // the copper in the 2D view's layer colours (studio_page.html's tokens)
    Object.assign(t, {cuF: css("--copper", d ? "#e8895a" : "#b45f2c"), cuB: css("--copperB", d ? "#6aa3ff" : "#2f6fb8"), cuIn: css("--copperIn", d ? "#5dc48a" : "#2e8b57"),
      planeF: css("--plane", d ? "#b8734a" : "#c98a5e"), via: css("--via", d ? "#c47a45" : "#7d4a22"), substrate: css("--substrate", d ? "#1b2025" : "#fbfbf8"),
      sevCritical: css("--sev-critical", d ? "#ff7a73" : "#c8312c"), sevWarning: css("--sev-warning-mark", d ? "#ffd400" : "#f2c200"), sevNotice: css("--sev-notice", d ? "#6f9cff" : "#2563eb"),
      bad: css("--bad", d ? "#ff7a73" : "#c8312c")});
    state.marksSig = "";                                     // the markers take the theme's colours at their next sync
    if (host.changed && state.sig) host.changed();
    state.theme = t;
    renderer.setClearColor(new THREE.Color(t.bg), 1);
    bodyLook();
    for (const m of state.copper) m.material.color.copy(copperColour(m.userData.cu));
    for (const v of state.vias) v.mesh.material.color.copy(copperColour(v.mesh.userData.cu));
    if (state.grid) state.grid.material.color.set(t.grid);
    if (state.plateMat) { state.plateMat.map.dispose(); state.plateMat.map = hatch(t.plate); state.plateMat.needsUpdate = true; }
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
    buildSheets(outer, loops);
    bodyLook();
  }
  // Spread, the body fades out and each copper layer gets a sheet of its own (bodyLook in studio_3d_core.js says how each is drawn).
  function clearSheets() {
    for (const s of state.sheets) state.root.remove(s);
    if (state.sheets.length) { state.sheets[0].geometry.dispose(); state.sheets[0].children[0].geometry.dispose(); }
    for (const s of state.sheets) { s.material.dispose(); s.children[0].material.dispose(); }
    state.sheets = [];
  }
  function buildSheets(outer, loops) {
    clearSheets();
    const names = state.stack ? state.stack.layers.map(l => l.name) : [];
    if (!outer || !names.length) return;
    const shape = new THREE.Shape(ring(outer));
    for (const l of loops) if (l !== outer) shape.holes.push(new THREE.Path(ring(l)));
    const fill = new THREE.ShapeGeometry(shape, 6);
    fill.rotateX(-Math.PI / 2);
    const pts = [];
    for (const l of loops) for (let i = 0; i < l.length; i++) { const a = l[i], b = l[(i + 1) % l.length]; pts.push(a[0], 0, a[1], b[0], 0, b[1]); }
    const edge = new THREE.BufferGeometry(); edge.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    for (const name of names) {
      const s = new THREE.Mesh(fill, new THREE.MeshBasicMaterial({color: new THREE.Color(state.theme.body), transparent: true, opacity: 0, depthWrite: false, side: THREE.DoubleSide}));
      s.add(new THREE.LineSegments(edge, new THREE.LineBasicMaterial({color: new THREE.Color(state.theme.edge), transparent: true, opacity: 0})));
      s.userData.layer = name; s.visible = false; s.renderOrder = -2;
      state.root.add(s); state.sheets.push(s);
    }
  }
  // Solid, or see-through: the body translucent, so the inner layers' copper shows through it; spread, the layers' sheets solid or faint.
  // The body is a volume round every layer, so no order of drawing puts it rightly behind and in front of them all: it is drawn first of the
  // translucent things, over the opaque copper inside it, and the zones' translucent fills after it.
  function bodyLook() {
    const t = state.theme, look = lookOf(state.bodyMode, state.spreadK), sh = look.sheet, b = look.body;
    for (const s of state.sheets) {
      const sm = s.material;
      s.visible = sh.visible;
      if (sm.transparent !== sh.transparent || sm.depthWrite !== sh.depthWrite) { sm.transparent = sh.transparent; sm.depthWrite = sh.depthWrite; sm.needsUpdate = true; }
      sm.opacity = sh.opacity; s.children[0].material.opacity = sh.edge;
      sm.color.set(t[sh.colour]); s.children[0].material.color.set(t.edge);
    }
    if (!state.body) return;
    const m = state.body.material;
    m.transparent = b.transparent; m.opacity = b.opacity; m.depthWrite = b.depthWrite; m.needsUpdate = true;
    m.color.set(t[b.colour]);
    state.body.renderOrder = b.order;
    state.body.visible = b.visible;
    request();
  }
  // A grid under the whole scene, as the 2D view has: a part that stands off the board (a part the generator left in its staging area) is
  // seen to have nothing under it.
  function buildGrid(plan) {
    if (state.grid) { state.root.remove(state.grid); state.grid.geometry.dispose(); state.grid.material.dispose(); state.grid = null; }
    const e = state.extent.slice();
    for (const it of plan.items || []) if (it.at) { e[0] = Math.min(e[0], it.at[0] - 3); e[1] = Math.min(e[1], it.at[1] - 3); e[2] = Math.max(e[2], it.at[0] + 3); e[3] = Math.max(e[3], it.at[1] + 3); }
    let step = 5;
    while ((e[2] - e[0]) / step > 160 || (e[3] - e[1]) / step > 160) step *= 2;
    const pts = [];
    const x0 = Math.floor(e[0] / step) * step, x1 = Math.ceil(e[2] / step) * step, z0 = Math.floor(e[1] / step) * step, z1 = Math.ceil(e[3] / step) * step;
    for (let x = x0; x <= x1; x += step) pts.push(x, 0, z0, x, 0, z1);
    for (let z = z0; z <= z1; z += step) pts.push(x0, 0, z, x1, 0, z);
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    state.grid = new THREE.LineSegments(g, new THREE.LineBasicMaterial({color: new THREE.Color(state.theme.grid), transparent: true, opacity: 0.6, depthWrite: false}));
    state.grid.position.y = -0.03;
    state.root.add(state.grid);
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
    if (state.plateMesh) { state.root.remove(state.plateMesh); state.plateMesh.geometry.dispose(); state.plateMat.map.dispose(); state.plateMat.dispose(); state.plateMesh = null; state.plateBase = null; }
    for (const p of state.plates) if (p.label) { state.root.remove(p.label); p.label.geometry.dispose(); p.label.material.map.dispose(); p.label.material.dispose(); }
    clearSel();
    state.groups = []; state.plates = [];
  }
  // A part with no model is a plate: its outline (plateOutline: its courtyard, else its body, else the box of its shapes) extruded a little off
  // its face, hatched. They are one mesh (one draw call) whatever their number; they are in step order, so the first k are a draw range.
  function plateOf(item, member, why, n, loading) {
    const {pts, back} = plateOutline(item, member);
    return {n, key: item.key, ref: member.ref, why, loading, pts, back, vstart: 0, vend: 0};
  }
  function buildPlates() {
    if (!state.plates.length) return;
    const T = state.T, th = host.settings().plate_mm || 0.1, t = state.theme;
    state.plates.sort((a, b) => a.n - b.n);
    const pos = [], nor = [], uv = [];
    let cur = 0;
    for (const pl of state.plates) {
      let g = new THREE.ExtrudeGeometry(new THREE.Shape(ring(pl.pts)), {depth: th, bevelEnabled: false});
      g.rotateX(-Math.PI / 2); g.translate(0, pl.back ? -th : T, 0);
      if (g.index) g = g.toNonIndexed();
      pl.vstart = cur;
      pos.push(...g.attributes.position.array); nor.push(...g.attributes.normal.array); uv.push(...g.attributes.uv.array);
      cur += g.attributes.position.count; pl.vend = cur;
      g.dispose();
      const xs = pl.pts.map(q => q[0]), ys = pl.pts.map(q => q[1]);
      pl.bbox = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
      const w = pl.bbox[2] - pl.bbox[0], h = pl.bbox[3] - pl.bbox[1];
      if (w >= 4 && h >= 1.5) {                                           // big enough to carry its words
        const s = Math.min(w, h * 4) * 0.9;
        const label = new THREE.Mesh(new THREE.PlaneGeometry(s, s / 4), new THREE.MeshBasicMaterial({map: labelTexture(pl.loading ? "loading" : "no model: " + pl.why, t.text), transparent: true, depthWrite: false}));
        label.rotation.x = -Math.PI / 2; label.position.set((pl.bbox[0] + pl.bbox[2]) / 2, (pl.back ? 0 : T + th) + 0.02, (pl.bbox[1] + pl.bbox[3]) / 2);
        if (pl.back) label.position.y = -th - 0.02;
        label.userData.y0 = label.position.y;
        pl.label = label; state.root.add(label);
      }
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    geo.setAttribute("normal", new THREE.Float32BufferAttribute(nor, 3));
    geo.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
    state.plateMat = new THREE.MeshBasicMaterial({map: hatch(t.plate), transparent: true, opacity: 0.85, side: THREE.DoubleSide, depthWrite: false});
    state.plateMesh = new THREE.Mesh(geo, state.plateMat);
    state.plateBase = Float32Array.from(geo.attributes.position.array);          // where each plate stands with the layers closed
    state.root.add(state.plateMesh);
  }
  // ---- copper: each layer at its height in the stackup (layerStack, from model_plan.py). One merged mesh per layer and kind: the tracks of
  // each origin, the pads (with the parts' own copper), each zone's fill with its outline; the vias one mesh per origin, cylinders through
  // the layers they join. The ops of a mesh are in the order they were laid, so what a replay position shows is a few index ranges
  // (visibleRanges), as the 2D drawing shows it.
  const LIFT = {zone: 0.01, track: 0.02, pad: 0.03, via: 0.035};   // drawn just off the layer, in this order, so coplanar copper does not fight
  const ROUTED_LIGHTER = 0.3;                                       // the router's copper is mixed this far toward white: the 3D form of its hollow 2D look
  const ZONE_OPACITY = 0.3, VIA_SEGS = 12;
  function copperColour(cu) {
    const t = state.theme, l = cu.layer;
    const c = cu.kind === "via" ? t.via : cu.kind === "zone" ? (l === "F.Cu" ? t.planeF : l === "B.Cu" ? t.cuB : t.cuIn) : (l === "F.Cu" ? t.cuF : l === "B.Cu" ? t.cuB : t.cuIn);
    const col = new THREE.Color(c);
    if (cu.origin === "routed") col.lerp(new THREE.Color(0xffffff), ROUTED_LIGHTER);
    return col;
  }
  // a convex outline (a track's ribbon), filled as a fan
  function addFan(b, poly, y) {
    const v0 = b.n;
    for (const p of poly) b.pos.push(p[0], y, p[1]);
    for (let i = 1; i < poly.length - 1; i++) b.idx.push(v0, v0 + i, v0 + i + 1);
    b.n += poly.length;
  }
  // any outline (a pad, a zone), triangulated
  function addPoly(b, poly, y) {
    const tris = THREE.ShapeUtils.triangulateShape(poly.map(p => new THREE.Vector2(p[0], p[1])), []), v0 = b.n;
    for (const p of poly) b.pos.push(p[0], y, p[1]);
    for (const t of tris) b.idx.push(v0 + t[0], v0 + t[1], v0 + t[2]);
    b.n += poly.length;
  }
  // a via: its barrel from its top layer to its bottom one and a ring at each end. Each vertex keeps the layer it belongs to (`li`) and its
  // distance off it (`off`), so the via follows its layers wherever they are drawn (placeVias).
  function addVia(b, op, names) {
    const [top, bot] = viaSpan(op, names), ends = [[names.indexOf(top), LIFT.via, 1], [names.indexOf(bot), -LIFT.via, -1]];
    const R = Math.max((op.size || 0.6) / 2, 0.02), r = Math.min(Math.max((op.drill || 0.3) / 2, 0.01), R * 0.9), cx = op.at[0], cz = op.at[1], S = VIA_SEGS;
    const vert = (x, z, nx, ny, nz, li, off) => { b.pos.push(x, 0, z); b.nor.push(nx, ny, nz); b.li.push(li); b.off.push(off); return b.n++; };
    const ring = [];
    for (const [li, off] of ends) { const row = []; for (let j = 0; j < S; j++) { const a = 2 * Math.PI * j / S, c = Math.cos(a), s = Math.sin(a); row.push(vert(cx + R * c, cz + R * s, c, 0, s, li, off)); } ring.push(row); }
    for (let j = 0; j < S; j++) { const k = (j + 1) % S; b.idx.push(ring[0][j], ring[1][j], ring[1][k], ring[0][j], ring[1][k], ring[0][k]); }
    for (const [li, off, up] of ends) {
      const o = [], n = [];
      for (let j = 0; j < S; j++) { const a = 2 * Math.PI * j / S, c = Math.cos(a), s = Math.sin(a); o.push(vert(cx + R * c, cz + R * s, 0, up, 0, li, off)); n.push(vert(cx + r * c, cz + r * s, 0, up, 0, li, off)); }
      for (let j = 0; j < S; j++) { const k = (j + 1) % S; b.idx.push(o[j], o[k], n[k], o[j], n[k], n[j]); }
    }
  }
  // ---- spread: the stack pulled apart by k (0 closed, 1 open), each layer [studio] 3d_spread_mm further from the next, the middle of the
  // stack where it was; the parts ride on the outer layers (front parts above the top one, back parts under the bottom one).
  const GAP = () => { const g = host.settings().spread_mm; return g > 0 ? g : 4; };
  const layerY = name => spreadHeight(state.stack, name, state.spreadK, GAP());
  // Everything that rides on the layers, placed for the spread now: copper, vias, marks, the parts and their plates, the layer sheets, the grid.
  function applySpread() {
    if (!state.stack) return;
    for (const m of state.copper) { const l = m.userData.cu.layer; if (l) m.position.y = layerY(l) - drawHeight(state.stack, l); }
    placeVias();
    placeMarks();
    const mtx = new THREE.Matrix4();
    for (const g of state.groups) { g.entries.forEach((e, i) => g.mesh.setMatrixAt(i, matOf(e, mtx))); g.mesh.instanceMatrix.needsUpdate = true; g.mesh.computeBoundingSphere(); }
    if (state.plateMesh && state.plateBase) {
      const pos = state.plateMesh.geometry.attributes.position;
      for (const pl of state.plates) { const d = partLift(pl.back); for (let v = pl.vstart; v < pl.vend; v++) pos.array[3 * v + 1] = state.plateBase[3 * v + 1] + d; }
      pos.needsUpdate = true; state.plateMesh.geometry.computeBoundingSphere();
      for (const pl of state.plates) if (pl.label) pl.label.position.y = pl.label.userData.y0 + partLift(pl.back);
    }
    for (const s of state.sheets) s.position.y = layerY(s.userData.layer);
    if (state.grid) state.grid.position.y = -0.03 - spreadLift(state.stack, state.spreadK, GAP());
    bodyLook();
    if (state.selKey) applySel();
    request();
  }
  const partLift = below => state.stack ? (below ? -1 : 1) * spreadLift(state.stack, state.spreadK, GAP()) : 0;
  // a part's instance matrix where it stands now: its own, lifted with its outer layer
  function matOf(e, out) { out.fromArray(e.matrix); out.elements[13] += partLift(e.below); return out; }
  function placeVias() {
    const names = state.stack.layers.map(l => l.name);
    for (const v of state.vias) {
      const pos = v.mesh.geometry.attributes.position;
      for (let i = 0; i < v.li.length; i++) pos.array[3 * i + 1] = layerY(names[v.li[i]]) + v.off[i];
      pos.needsUpdate = true; v.mesh.geometry.computeBoundingSphere();
    }
  }
  function clearCopper() {
    for (const m of state.copper) {
      state.root.remove(m); m.geometry.dispose(); m.material.dispose();
      for (const c of m.children) { c.geometry.dispose(); c.material.dispose(); }
    }
    state.copper = []; state.vias = [];
  }
  function copperMesh(b) {
    const cu = b.cu, g = new THREE.BufferGeometry(), full = b.n > 65535 ? new Uint32Array(b.idx) : new Uint16Array(b.idx);
    g.setAttribute("position", new THREE.Float32BufferAttribute(b.pos, 3));
    g.setIndex(new THREE.BufferAttribute(full, 1));
    let mat;
    if (cu.kind === "via") { g.setAttribute("normal", new THREE.Float32BufferAttribute(b.nor, 3)); mat = new THREE.MeshStandardMaterial({color: copperColour(cu), roughness: 0.4, metalness: 0.3, side: THREE.DoubleSide}); }
    else if (cu.kind === "zone") mat = new THREE.MeshBasicMaterial({color: copperColour(cu), transparent: true, opacity: ZONE_OPACITY, depthWrite: false, side: THREE.DoubleSide});
    else mat = new THREE.MeshBasicMaterial({color: copperColour(cu), side: THREE.DoubleSide});
    const m = new THREE.Mesh(g, mat);
    m.userData.cu = Object.assign(cu, {spans: b.spans, full, shown: null, empty: false});
    if (cu.kind === "zone") {                                   // its outline, as the 2D view strokes it
      const y = b.pos[1], pts = [];
      for (const p of cu.pts) pts.push(p[0], y, p[1]);
      const lg = new THREE.BufferGeometry(); lg.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
      m.add(new THREE.LineLoop(lg, new THREE.LineBasicMaterial({color: copperColour(cu)})));
    }
    if (cu.kind === "via") state.vias.push({mesh: m, li: Int16Array.from(b.li), off: Float32Array.from(b.off)});
    g.computeBoundingSphere();
    return m;
  }
  function buildCopper(plan, order) {
    clearCopper();
    const stack = layerStack(plan), names = stack.layers.map(l => l.name);
    state.stack = stack;
    if (!names.length) return;
    const info = host.copper ? host.copper() : null, ops = plan.copper || [];
    state.cn = info ? info.n : 0;
    const stepOf = i => (info && info.steps[i]) || {s: 0, x: null};
    const originOf = i => info ? info.origins[i] : (ops[i].origin === "routed" ? "routed" : "planned");
    const builds = new Map();
    const get = (key, cu) => { let b = builds.get(key); if (!b) { b = {pos: [], nor: [], li: [], off: [], idx: [], spans: [], n: 0, cu}; builds.set(key, b); } return b; };
    const bottom = names[names.length - 1];
    const yOf = (layer, kind) => { const h = drawHeight(stack, layer); return h == null ? null : h + (layer === bottom && names.length > 1 ? -1 : 1) * LIFT[kind]; };
    const span = (b, st, i0) => b.spans.push({s: st.s, x: st.x, i0, i1: b.idx.length});
    for (const i of ops.map((c, i) => i).sort((a, b) => stepOf(a).s - stepOf(b).s || a - b)) {
      const c = ops[i], st = stepOf(i), org = originOf(i);
      if (c.t === "track" && c.a && c.b) {
        const y = yOf(c.layer, "track");
        if (y == null) continue;
        const b = get("t|" + c.layer + "|" + org, {kind: "track", layer: c.layer, origin: org}), i0 = b.idx.length;
        for (const poly of trackPolys(c, 5)) addFan(b, poly, y);
        span(b, st, i0);
      } else if ((c.t === "plane" || c.t === "pour") && (c.points || []).length >= 3) {
        const y = yOf(c.layer, "zone");
        if (y == null) continue;
        const b = get("z|" + i, {kind: "zone", layer: c.layer, origin: org, zone: i, pts: c.points}), i0 = b.idx.length;
        addPoly(b, c.points, y);
        span(b, st, i0);
      } else if (c.t === "via" && c.at) {
        const b = get("v|" + org, {kind: "via", origin: org}), i0 = b.idx.length;
        addVia(b, c, names);
        span(b, st, i0);
      }
    }
    // the pads and the parts' own copper, on each layer they are on, in the order the parts were placed
    const nOf = partSteps(order), pads = [];
    for (const it of plan.items || []) {
      const n = nOf.get(it.key);
      if (n == null) continue;
      for (const m of it.members || []) for (const s of m.shapes || []) if ((s.kind === "pad" || s.kind === "through" || s.kind === "copper") && s.poly && s.poly.length >= 3) pads.push({n, s});
    }
    pads.sort((a, b) => a.n - b.n);
    for (const {n, s} of pads) {
      let ls = s.kind === "through" ? (s.layers || []).filter(l => names.includes(l)) : [(s.layers || [])[0] || ((s.faces || [])[0] === "back" ? "B.Cu" : "F.Cu")];
      if (s.kind === "through" && !ls.length) ls = [names[0], bottom];
      for (const l of ls) {
        const y = yOf(l, "pad");
        if (y == null) continue;
        const kind = s.kind === "copper" ? "fcu" : "pad", b = get(kind + "|" + l, {kind, layer: l}), i0 = b.idx.length;
        addPoly(b, s.poly, y);
        const last = b.spans[b.spans.length - 1];
        if (last && last.s === n && last.i1 === i0) last.i1 = b.idx.length; else b.spans.push({s: n, x: null, i0, i1: b.idx.length});
      }
    }
    for (const b of builds.values()) { const m = copperMesh(b); state.copper.push(m); state.root.add(m); }
    placeVias();
    visibility();
  }
  // Show copper at replay position k: a mesh draws its visible index ranges, one range as a draw range, several as an index made of them.
  function applyRanges(m, ranges) {
    const cu = m.userData.cu, key = ranges.map(r => r[0] + "-" + r[1]).join(",");
    if (key !== cu.shown) {
      cu.shown = key; cu.empty = !ranges.length;
      const g = m.geometry;
      if (ranges.length === 1 && ranges[0][0] === 0) {
        if (g.index.array !== cu.full) g.setIndex(new THREE.BufferAttribute(cu.full, 1));
        g.setDrawRange(0, ranges[0][1]);
      } else if (ranges.length) {
        const out = new cu.full.constructor(ranges.reduce((s, r) => s + r[1] - r[0], 0));
        let at = 0;
        for (const [a, b] of ranges) { out.set(cu.full.subarray(a, b), at); at += b - a; }
        g.setIndex(new THREE.BufferAttribute(out, 1)); g.setDrawRange(0, Infinity);
      }
    }
    m.visible = !cu.empty && !cu.off;
  }
  function showCopper(k) {
    for (const m of state.copper) {
      const cu = m.userData.cu;
      applyRanges(m, cu.kind === "pad" || cu.kind === "fcu" ? visibleRanges(cu.spans, k, Infinity) : visibleRanges(cu.spans, k, state.cn));
    }
  }
  // The legend's switches, the page's own (host.off): the same set hides the same copper in 2D and 3D.
  function visibility() {
    const off = host.off ? host.off() : new Set();
    for (const m of state.copper) { const cu = m.userData.cu; cu.off = !copperShown(cu, off); m.visible = !cu.empty && !cu.off; }
    marksVisibility();
  }

  // ---- marks: each finding placed on the board is a marker at its place and its layer's height (findingLayer), in its severity's colour
  // (the page's tokens), drawn over everything; the congestion map is a translucent sheet over the top layer, cell by cell in the 2D
  // overlay's colours (host.heat), with the most congested cell ringed. The map is of every routing layer together (RUDY), so it lies on
  // the top one, under its copper as 2D draws it under the copper. Both are switched by the legend's Marks rows and hidden while a replay
  // is under way, as in 2D.
  const MARK_PX = 14, MARK_ON_PX = 26, MARK_PICK_PX = 10, HEAT_OPACITY = 0.6, HEAT_LIFT = 0.005, MARK_LIFT = 0.1;
  state.marks = []; state.markObjs = []; state.heat = null;
  function dotTexture(ring) {
    const c = document.createElement("canvas"); c.width = c.height = 64;
    const g = c.getContext("2d");
    g.beginPath(); g.arc(32, 32, ring ? 26 : 24, 0, 2 * Math.PI);
    if (ring) { g.strokeStyle = "#ffffff"; g.lineWidth = 8; g.stroke(); }
    else { g.fillStyle = "#ffffff"; g.fill(); g.strokeStyle = "#10151b"; g.lineWidth = 6; g.stroke(); }
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
    return t;
  }
  function clearMarks() {
    for (const o of state.markObjs) { state.root.remove(o); o.geometry.dispose(); if (o.material.map) o.material.map.dispose(); o.material.dispose(); for (const c of o.children) { c.geometry.dispose(); c.material.dispose(); } }
    state.markObjs = []; state.marks = []; state.heat = null; state.markSel = null;
  }
  const markY = m => layerY(m.layer) + (m.layer === state.stack.layers[state.stack.layers.length - 1].name && state.stack.layers.length > 1 ? -MARK_LIFT : MARK_LIFT);
  function buildMarks(plan) {
    clearMarks();
    const names = state.stack ? state.stack.layers.map(l => l.name) : [];
    if (!names.length) return;
    const t = state.theme, sevCol = {critical: t.sevCritical, warning: t.sevWarning, notice: t.sevNotice};
    state.marks = (host.findings ? host.findings() : []).map(m => ({i: m.i, sev: m.sev, at: m.at, on: m.on, layer: findingLayer(m, names)}));
    const points = (ms, col, px, ring, order) => {
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.Float32BufferAttribute(ms.flatMap(m => [m.at[0], markY(m), m.at[1]]), 3));
      const p = new THREE.Points(g, new THREE.PointsMaterial({color: new THREE.Color(col), size: px, sizeAttenuation: false, map: dotTexture(ring), transparent: true, alphaTest: 0.05, depthTest: false, depthWrite: false}));
      p.renderOrder = order; p.userData.marks = ms; p.userData.kind = "finding"; p.frustumCulled = false;
      state.root.add(p); state.markObjs.push(p);
      return p;
    };
    ["notice", "warning", "critical"].forEach((sev, n) => { const ms = state.marks.filter(m => m.sev === sev); if (ms.length) points(ms, sevCol[sev], MARK_PX, false, 10 + n); });      // the worst drawn last, on top
    const on = state.marks.filter(m => m.on);
    if (on.length) state.markSel = points(on, t.accent, MARK_ON_PX, true, 20);
    const c = plan.congestion;
    if (c && c.cells && c.cells.length && host.heat) {
      const cs = c.cell, n = c.cells.length, pos = new Float32Array(n * 12), col = new Float32Array(n * 12), idx = new Uint32Array(n * 6), tmp = new THREE.Color();
      c.cells.forEach(([i, j, u], k) => {
        const x0 = c.origin[0] + i * cs, z0 = c.origin[1] + j * cs;
        pos.set([x0, 0, z0, x0 + cs, 0, z0, x0 + cs, 0, z0 + cs, x0, 0, z0 + cs], k * 12);
        tmp.setStyle(host.heat(u));
        for (let v = 0; v < 4; v++) col.set([tmp.r, tmp.g, tmp.b], k * 12 + v * 3);
        idx.set([k * 4, k * 4 + 1, k * 4 + 2, k * 4, k * 4 + 2, k * 4 + 3], k * 6);
      });
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(pos, 3)); g.setAttribute("color", new THREE.BufferAttribute(col, 3)); g.setIndex(new THREE.BufferAttribute(idx, 1));
      const sheet = new THREE.Mesh(g, new THREE.MeshBasicMaterial({vertexColors: true, transparent: true, opacity: HEAT_OPACITY, depthWrite: false, side: THREE.DoubleSide}));
      sheet.renderOrder = 5; sheet.userData.kind = "heat";
      if (c.worst_at) {
        const ring = [], r = cs * 1.6;
        for (let a = 0; a < 32; a++) ring.push(c.worst_at[0] + r * Math.cos(a / 16 * Math.PI), 0.01, c.worst_at[1] + r * Math.sin(a / 16 * Math.PI));
        const lg = new THREE.BufferGeometry(); lg.setAttribute("position", new THREE.Float32BufferAttribute(ring, 3));
        sheet.add(new THREE.LineLoop(lg, new THREE.LineBasicMaterial({color: new THREE.Color(t.bad)})));
      }
      g.computeBoundingSphere();
      state.root.add(sheet); state.markObjs.push(sheet); state.heat = sheet;
    }
    placeMarks();
    marksVisibility();
  }
  function placeMarks() {
    for (const o of state.markObjs) {
      if (o.userData.kind === "finding") {
        const pos = o.geometry.attributes.position;
        o.userData.marks.forEach((m, n) => { pos.array[3 * n + 1] = markY(m); });
        pos.needsUpdate = true;
      } else if (o.userData.kind === "heat") o.position.y = layerY(state.stack.layers[0].name) + HEAT_LIFT;
    }
  }
  function marksVisibility() {
    const off = host.off ? host.off() : new Set(), replaying = state.k != null && state.k < state.cn;
    for (const o of state.markObjs) o.visible = !replaying && !off.has(o.userData.kind === "heat" ? "heat" : "findings");
    request();
  }
  // The findings under the pointer, by their markers' places on the screen.
  function marksAt(ev) {
    const shown = state.markObjs.some(o => o.userData.kind === "finding" && o.visible);
    if (!shown) return [];
    const r = canvas.getBoundingClientRect(), v = new THREE.Vector3(), pts = [];
    for (const m of state.marks) {
      v.set(m.at[0], markY(m), m.at[1]).project(camera);
      if (v.z > 1) continue;
      pts.push({i: m.i, x: (v.x + 1) / 2 * r.width, y: (1 - v.y) / 2 * r.height});
    }
    return pickMarks(pts, ev.clientX - r.left, ev.clientY - r.top, MARK_PICK_PX);
  }

  const plateAt = vertex => { let lo = 0, hi = state.plates.length - 1; while (lo <= hi) { const mid = (lo + hi) >> 1, p = state.plates[mid]; if (vertex < p.vstart) hi = mid - 1; else if (vertex >= p.vend) lo = mid + 1; else return p; } return null; };

  function rebuild(plan, order) {
    clearParts();
    const T = state.T;
    const nOf = partSteps(order);
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
                g.entries.push({n, key: it.key, ref: m.ref, matrix: e.matrix, below: e.matrix[13] < state.T / 2});     // the model's origin under the board's mid-plane: a part on the back
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
        if (!drawn) state.plates.push(plateOf(it, m, why || "no model declared", n, why === "loading"));
      }
    }
    for (const g of byGroup.values()) {
      g.entries.sort((a, b) => a.n - b.n);
      g.ns = g.entries.map(e => e.n);
      const mesh = new THREE.InstancedMesh(g.mat.geometry, g.mat.mat, g.entries.length);
      const mtx = new THREE.Matrix4();
      g.entries.forEach((e, i) => { mesh.setMatrixAt(i, matOf(e, mtx)); });
      mesh.instanceMatrix.needsUpdate = true;
      mesh.userData.group = g; g.mesh = mesh; mesh.frustumCulled = false;
      mesh.computeBoundingSphere();
      state.root.add(mesh);
      state.groups.push(g);
    }
    buildPlates();
    state.tris = state.groups.reduce((s, g) => s + g.entries.length * g.mat.tris, 0);
    state.over = state.tris > (host.settings().max_tris || 4000000);
    state.loadingParts = dueLoading;
  }

  // the first k steps are a count of each group's instances
  function showSteps(k) {
    state.k = k;
    const lim = k == null ? Infinity : k;
    for (const g of state.groups) { g.mesh.count = state.over ? 0 : upper(g.ns, lim); }
    if (state.plateMesh) {
      const shown = upper(state.plates.map(p => p.n), lim);
      state.plateMesh.geometry.setDrawRange(0, shown ? state.plates[shown - 1].vend : 0);
      for (const p of state.plates) if (p.label) p.label.visible = p.n < lim;
    }
    showCopper(k);
    marksVisibility();
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
    if (state.plateMat) state.plateMat.opacity = key ? 0.35 : 0.85;
    if (!key) { request(); return; }
    for (const g of state.groups) {
      const es = g.entries.filter(e => e.key === key && e.n < (state.k == null ? Infinity : state.k));
      if (!es.length) continue;
      const m = new THREE.InstancedMesh(g.mat.geometry, g.mat.mat, es.length);
      const mtx = new THREE.Matrix4();
      es.forEach((e, i) => { m.setMatrixAt(i, matOf(e, mtx)); });
      m.instanceMatrix.needsUpdate = true; m.frustumCulled = false;
      state.root.add(m); state.selObjs.push(m);
    }
    for (const pl of state.plates) if (pl.key === key && pl.n < (state.k == null ? Infinity : state.k)) {         // a selected plate is drawn whole, in the accent colour
      const g = new THREE.BufferGeometry(), src = state.plateMesh.geometry.attributes;
      g.setAttribute("position", new THREE.Float32BufferAttribute(src.position.array.slice(pl.vstart * 3, pl.vend * 3), 3));
      const m = new THREE.Mesh(g, new THREE.MeshBasicMaterial({color: new THREE.Color(state.theme.accent), transparent: true, opacity: 0.6, depthWrite: false}));
      m.userData.own = true; state.root.add(m); state.selObjs.push(m);
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
      const h = g.asset.header.bbox; matOf(e, mtx);
      for (const x of [h[0], h[3]]) for (const y of [h[1], h[4]]) for (const z of [h[2], h[5]]) b.expandByPoint(v.set(x, y, z).applyMatrix4(mtx));
    }
    const th = host.settings().plate_mm || 0.1;
    for (const p of state.plates) if (p.key === key) { const y = (p.back ? -th : state.T) + partLift(p.back); b.expandByPoint(v.set(p.bbox[0], y, p.bbox[1])); b.expandByPoint(v.set(p.bbox[2], y + th, p.bbox[3])); }
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
    state.userMoved = false; state.fitExtent = state.extent.join(",");
  }
  function fit() { setView(state.viewName || "iso"); }

  // ---- picking
  const ray = new THREE.Raycaster();
  function pick(ev) {
    const r = canvas.getBoundingClientRect();
    ray.setFromCamera(new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1), camera);
    const objs = [];
    for (const g of state.groups) if (g.mesh.count) objs.push(g.mesh);
    if (state.plateMesh) objs.push(state.plateMesh);
    const hits = ray.intersectObjects(objs, false);
    for (const h of hits) {
      if (h.object.userData.group) { const e = h.object.userData.group.entries[h.instanceId]; if (e) return {key: e.key, ref: e.ref}; }
      else if (h.object === state.plateMesh && h.faceIndex != null) { const pl = plateAt(h.faceIndex * 3); if (pl) return {key: pl.key, ref: pl.ref}; }
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
    const fi = marksAt(e);
    if (fi.length) { host.selectFindings(fi); return; }
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
    const fi = marksAt(e);
    if (fi.length && host.hoverFindings) { host.hoverFindings(fi, e.clientX, e.clientY); return; }
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
        matOf(a.entry, mtx);
        lift.makeTranslation(0, (a.entry.below ? -4 : 4) * (1 - e), 0);     // a back part rises to the board from underneath
        a.group.mesh.setMatrixAt(a.i, lift.multiply(mtx));
        a.group.mesh.instanceMatrix.needsUpdate = true;
        return t < 1;
      });
      animating = state.animations.length > 0;
    }
    if (state.spreadK !== state.spreadTo) {                           // the layers parting or closing, eased in and out
      const ms = host.settings().spread_ms == null ? 450 : host.settings().spread_ms, t = ms > 0 ? Math.min(1, Math.max(0, (now - state.spreadT0) / ms)) : 1;
      const e = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
      state.spreadK = t >= 1 ? state.spreadTo : state.spreadFrom + (state.spreadTo - state.spreadFrom) * e;
      applySpread();
      animating = animating || state.spreadK !== state.spreadTo;
    }
    if (state.loadingParts) {                                         // plates of models still converting pulse faintly
      const o = 0.5 + 0.25 * Math.sin(now / 350);
      if (state.plateMat && !state.selKey) state.plateMat.opacity = o + 0.3;
      animating = true;
    }
    renderer.render(scene, camera);
    const info = renderer.info.render;
    state.stats = {calls: info.calls, triangles: info.triangles, groups: state.groups.length, plates: state.plates.length, instances: state.groups.reduce((s, g) => s + g.mesh.count, 0), over: state.over,
      copper: state.copper.length};
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
        "#" + order.length + "#" + Object.values(host.models() || {}).map(v => v.state[0]).join("") + "#" + state.assets.size + "#" + ((plan.board && plan.board.loops || []).length) + "#" + (plan.copper || []).filter(c => c.t === "via").length +
        "#" + (plan.copper || []).length + "#" + JSON.stringify((plan.stackup && plan.stackup.layers) || plan.layers || []);
      let fresh = [];
      if (sig !== state.sig) {
        const first = !state.sig;
        const before = new Set(state.seen);
        state.stack = layerStack(plan);
        if (!state.body || (state.bodySig !== boardSig(plan))) { buildBody(plan); state.bodySig = boardSig(plan); }
        rebuild(plan, order);
        buildCopper(plan, order);
        const gsig = state.extent.join(",") + "|" + (plan.items || []).reduce((s, i) => s + (i.at ? Math.round(i.at[0] / 5) + Math.round(i.at[1] / 5) * 7 : 0), 0) + "|" + state.theme.grid;
        if (gsig !== state.gridSig) { buildGrid(plan); state.gridSig = gsig; }
        state.sig = sig;
        state.seen = new Set((plan.items || []).map(i => i.key));
        fresh = first || !opts.animate ? [] : [...state.seen].filter(k => !before.has(k));
        if (first || (!state.userMoved && state.fitExtent !== state.extent.join(","))) { setView(state.viewName || "iso"); }      // the board grows while a resolve fits it: the view follows until someone moves it
      }
      const fsig = (host.findings ? host.findings() : []).map(m => m.i + (m.on ? "*" : "")).join(",") + "#" + (plan.congestion ? plan.congestion.cells.length + ":" + plan.congestion.worst : "") +
        "#" + JSON.stringify(state.stack && state.stack.layers.map(l => l.name));
      if (sig !== state.lastMarkSig || fsig !== state.marksSig) { buildMarks(plan); state.marksSig = fsig; state.lastMarkSig = sig; if (state.spreadK) applySpread(); }
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
    // "solid" or "see" (see-through: the body translucent)
    body(mode) { state.bodyMode = mode === "see" ? "see" : "solid"; bodyLook(); },
    // the legend's switches changed (host.off)
    visibility,
    // pull the layers apart (true) or close them up, over [studio] 3d_spread_ms
    spread(on) {
      const to = on ? 1 : 0;
      if (to === state.spreadTo) return;
      state.spreadFrom = state.spreadK; state.spreadTo = to; state.spreadT0 = performance.now();
      request();
    },
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
  const boardSig = plan => JSON.stringify([plan.board && plan.board.loops, state.T, layerStack(plan).layers.map(l => l.name)]) + (plan.copper || []).filter(c => c.t === "via").length;
  theme();
  resize();
  return api;
}
