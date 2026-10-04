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
