// The 3D view's pure parts, with no three.js in them so they can be tested on their own (tests/test_studio_3d_core.py runs them in node):
// the mesh file reader, and what the replay position shows.

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

export const upper = (arr, k) => { let lo = 0, hi = arr.length; while (lo < hi) { const mid = (lo + hi) >> 1; if (arr[mid] < k) lo = mid + 1; else hi = mid; } return lo; };   // how many of a sorted array are below k


// The outline a part with no model is drawn as (a plate) and the face it is on: its courtyard; else its body (a document from a run's records
// carries no courtyard for a part that is spaced by what it draws); else the box of its shapes; else a small marker at its item.
export function plateOutline(item, member) {
  const shapes = member.shapes || [], face = s => (s.faces || [item.face || "front"])[0] === "back";
  const own = shapes.find(s => s.kind === "courtyard" && s.poly && s.poly.length >= 3) || shapes.find(s => s.kind === "body" && s.poly && s.poly.length >= 3);
  if (own) return {pts: own.poly, back: face(own)};
  const drawn = shapes.filter(s => s.poly && s.poly.length);
  if (drawn.length) {
    const xs = drawn.flatMap(s => s.poly.map(p => p[0])), ys = drawn.flatMap(s => s.poly.map(p => p[1]));
    const x0 = Math.min(...xs), y0 = Math.min(...ys), x1 = Math.max(...xs), y1 = Math.max(...ys);
    return {pts: [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], back: face(drawn[0])};
  }
  const at = item.at || [0, 0], r = 0.6, q = v => Math.round(v * 1000) / 1000;
  return {pts: [[q(at[0] - r), q(at[1] - r)], [q(at[0] + r), q(at[1] - r)], [q(at[0] + r), q(at[1] + r)], [q(at[0] - r), q(at[1] + r)]], back: item.face === "back"};
}

// The replay step number of each placed item: the position its first step has in the page's replaySteps order.
export function partSteps(order) {
  const n = new Map();
  for (const s of order) if (s.type === "place" && !n.has(s.item)) n.set(s.item, s.n);
  return n;
}

// The item keys shown at replay position k (null: all): the same set the 2D drawing shows, by the same rule (the first k placement steps).
export function visibleKeys(plan, order, k) {
  const lim = k == null ? Infinity : k, n = partSteps(order);
  return (plan.items || []).filter(it => n.has(it.key) && n.get(it.key) < lim).map(it => it.key);
}

// ---- copper
const r4 = v => Math.round(v * 10000) / 10000;
const layerRank = l => l === "F.Cu" ? -1 : l === "B.Cu" ? 99 : parseInt(String(l).slice(2)) || 50;
// The plan's copper layer names top to bottom: its `layers`, else the layers its copper is on.
export function copperNames(plan) {
  const have = plan && plan.layers && plan.layers.length ? plan.layers : [...new Set(((plan && plan.copper) || []).map(c => c.layer).filter(Boolean))];
  return have.slice().sort((a, b) => layerRank(a) - layerRank(b));
}

// The copper layers top to bottom, each with the height of its middle (`z`, mm, 0 the back face) and thickness (`t`), as the plan's stackup
// gives them (model_plan.py); a plan without them (an older worker, a command's stream) has its layers spaced evenly through the thickness,
// the outer ones on the faces.
export function layerStack(plan) {
  const st = (plan && plan.stackup) || {}, T = st.thickness || 1.6;
  if (st.layers && st.layers.length) return {T, layers: st.layers.map(l => ({name: l.name, z: l.z, t: l.thickness == null ? null : l.thickness})), declared: !!st.declared};
  const names = copperNames(plan), last = Math.max(names.length - 1, 1);
  return {T, layers: names.map((n, i) => ({name: n, z: r4(T * (1 - i / last)), t: null})), declared: false};
}

// Where a layer's copper is drawn: the outer layers on the board's faces (the body is drawn the full thickness), an inner one at its height.
export function drawHeight(stack, name) {
  const i = stack.layers.findIndex(l => l.name === name);
  if (i < 0) return null;
  if (i === 0) return stack.T;
  if (i === stack.layers.length - 1) return 0;
  return stack.layers[i].z;
}

// Spread by k (0 closed, 1 open): each layer moves gap * k further from the next, the middle of the stack staying where it is.
export function spreadHeight(stack, name, k, gap) {
  const i = stack.layers.findIndex(l => l.name === name), n = stack.layers.length;
  if (i < 0) return null;
  return drawHeight(stack, name) + k * gap * ((n - 1) / 2 - i);
}
// How far the top layer has risen (the bottom one sunk) at spread k: front parts ride on the top layer, back parts under the bottom one.
export const spreadLift = (stack, k, gap) => k * gap * Math.max(stack.layers.length - 1, 0) / 2;

// The layers a via joins, top and bottom: its own (`layers`), else the whole stack (a through via, or a route's via, which names none).
export function viaSpan(op, names) {
  const own = (op.layers || []).filter(l => names.includes(l)).sort((a, b) => names.indexOf(a) - names.indexOf(b));
  return own.length ? [own[0], own[own.length - 1]] : [names[0], names[names.length - 1]];
}

// A track as convex outlines to fill: a ribbon of its width with round ends; an arc (`mid` on it) a chain of them along the circle.
function capsule(a, b, r, segs) {
  let dx = b[0] - a[0], dy = b[1] - a[1];
  const len = Math.hypot(dx, dy);
  if (len < 1e-9) { dx = 1; dy = 0; } else { dx /= len; dy /= len; }
  const fn = Math.atan2(dx, -dy), out = [];                                  // the angle of the normal (-dy, dx)
  for (let j = 0; j <= segs; j++) { const t = fn - Math.PI * j / segs; out.push([b[0] + r * Math.cos(t), b[1] + r * Math.sin(t)]); }
  for (let j = 0; j <= segs; j++) { const t = fn - Math.PI - Math.PI * j / segs; out.push([a[0] + r * Math.cos(t), a[1] + r * Math.sin(t)]); }
  return out;
}
function arcPoints(a, m, b) {
  const d = 2 * (a[0] * (m[1] - b[1]) + m[0] * (b[1] - a[1]) + b[0] * (a[1] - m[1]));
  if (Math.abs(d) < 1e-12) return [a, b];
  const sq = p => p[0] * p[0] + p[1] * p[1];
  const cx = (sq(a) * (m[1] - b[1]) + sq(m) * (b[1] - a[1]) + sq(b) * (a[1] - m[1])) / d, cy = (sq(a) * (b[0] - m[0]) + sq(m) * (a[0] - b[0]) + sq(b) * (m[0] - a[0])) / d;
  const r = Math.hypot(a[0] - cx, a[1] - cy), ang = p => Math.atan2(p[1] - cy, p[0] - cx), TAU = 2 * Math.PI;
  const a0 = ang(a), am = ((ang(m) - a0) % TAU + TAU) % TAU, ab = ((ang(b) - a0) % TAU + TAU) % TAU;
  const sweep = am < ab ? ab : ab - TAU;                                       // the way round that passes the middle point
  const n = Math.max(2, Math.ceil(Math.abs(sweep) / (Math.PI / 18)));
  const out = [];
  for (let i = 0; i <= n; i++) { const t = a0 + sweep * i / n; out.push([cx + r * Math.cos(t), cy + r * Math.sin(t)]); }
  return out;
}
export function trackPolys(op, segs = 6) {
  const r = (op.width || 0.1) / 2;
  if (!op.mid) return [capsule(op.a, op.b, r, segs)];
  const pts = arcPoints(op.a, op.mid, op.b), out = [];
  for (let i = 1; i < pts.length; i++) out.push(capsule(pts[i - 1], pts[i], r, segs));
  return out;
}

// The index ranges of a copper mesh to draw at replay position k of n: `spans` are its ops in the order they were laid ({s, x, i0, i1}: the
// position that lays it, the one that rips it up again or null, its indices). As the 2D drawing: all of it but what was ripped up when the
// replay is at its end; nothing while a plan's replay is under way; a route's replay ("laid": each op has its step) lays and rips each op
// at its step.
export function visibleRanges(spans, k, n, laid) {
  const replaying = k != null && k < n;
  if (replaying && !laid) return [];
  const kk = replaying ? k : n, out = [];
  for (const sp of spans) {
    if (!(sp.s < kk && (sp.x == null || kk <= sp.x))) continue;
    const l = out[out.length - 1];
    if (l && l[1] === sp.i0) l[1] = sp.i1; else out.push([sp.i0, sp.i1]);
  }
  return out;
}

// Whether the legend's switches (`off`, the page's set of what is switched off) leave a copper mesh shown, as the 2D view's rules hide the
// same copper (visRules): a layer's row takes its tracks, zones, pads and the parts' own copper; an origin's row its tracks, zones and vias;
// a zone's row that zone; the pads row the pads; the vias row the vias.
export function copperShown(cu, off) {
  if (cu.layer && off.has("cu:" + cu.layer)) return false;
  if (cu.origin && off.has("org:" + cu.origin)) return false;
  if (cu.kind === "zone" && off.has("z:" + cu.zone)) return false;
  if (cu.kind === "pad" && off.has("pad")) return false;
  if (cu.kind === "via" && off.has("via")) return false;
  return true;
}
