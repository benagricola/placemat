"use strict";
// The studio's board builder, page side. Loaded by studio_page.html (one script tag); everything here is the Build mode: the start
// view's list of boards with no layout, a full-screen flow for a new board (the board, its facts, its outline), and a Build tab with
// the parts list, the relation menu, the timeline. The page only draws what the server returns and sends back what the user chose:
// records, never source text. It reaches the studio page through its globals (S, T, esc, $, es, render, renderPicker, goTab,
// showNarrow, schedule) and adds its own elements.
(() => {
const BS = {
  st: null, facts: null, parts: null, offers: null, subj: [], target: null, chip: "edge", form: null, ol: null, step: "board",
  filter: {status: "", text: ""}, msg: null, diff: null, tried: null, turns: null, olAffected: null, closed: false, params: {},
  acks: {}, picking: false, applying: false, lastSide: null,
};
const SIDES = ["NORTH", "EAST", "SOUTH", "WEST"];
const SIDE_WORD = {NORTH: "north", EAST: "east", SOUTH: "south", WEST: "west"};
const OZ_MM = 0.035;
const h = (s) => esc(s);
const q = (sel, root) => (root || document).querySelector(sel);
const qa = (sel, root) => [...(root || document).querySelectorAll(sel)];

// ---------------------------------------------------------------- calls
function api(method, path, body) {
  const url = path + (path.includes("?") ? "&" : "?") + "t=" + encodeURIComponent(T);
  return fetch(url, {method, headers: {"Content-Type": "application/json"}, body: method === "POST" ? JSON.stringify(body || {}) : undefined})
    .then(r => r.json().catch(() => ({})).then(j => {
      if (!r.ok) { const e = new Error(j.error || ("HTTP " + r.status)); e.data = j; e.status = r.status; throw e; }
      return j;
    }));
}
const post = (path, body) => api("POST", path, body);
const get = (path) => api("GET", path);
function say(text, kind) { BS.msg = text ? {text, kind: kind || "info"} : null; drawMsg(); }
function fail(e) { say(e.message, "bad"); return null; }

// ---------------------------------------------------------------- styles
const css = document.createElement("style");
css.textContent = `
#bld { position: fixed; inset: 0; z-index: 60; background: var(--bg); display: flex; flex-direction: column; }
#bld[hidden] { display: none; }
#bld .bh { display: flex; align-items: center; gap: 10px; padding: 8px 14px; background: var(--surface); border-bottom: 1px solid var(--line); flex-wrap: wrap; }
#bld .bh b { font-size: 15px; }
#bld .steps { display: flex; gap: 4px; margin-left: 8px; }
#bld .steps button, .bld-btn { border: 1px solid var(--line); background: var(--surface); border-radius: 7px; padding: 5px 11px; min-height: 30px; }
#bld .steps button.on { border-color: var(--accent); background: var(--accent-soft); font-weight: 600; }
.bld-btn.primary { background: var(--accent); color: #fff; border-color: var(--accent); }
.bld-btn[disabled] { opacity: .5; cursor: default; }
.bld-btn.good { background: var(--good-soft); color: var(--good); border-color: var(--good); }
#bld .bb { flex: 1; overflow: auto; padding: 16px; }
.bld-wrap { max-width: 1100px; margin: 0 auto; display: grid; gap: 16px; }
.bld-card { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; }
.bld-card h3 { margin: 0 0 8px; font-size: 14px; }
.bld-card h4 { margin: 10px 0 4px; font-size: 12.5px; color: var(--dim); font-weight: 600; }
.bld-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px 12px; }
.bld-f { display: flex; flex-direction: column; gap: 2px; font-size: 12px; color: var(--dim); }
.bld-f input, .bld-f select, .bld-in { font: inherit; color: var(--ink); background: var(--bg); border: 1px solid var(--line); border-radius: 6px; padding: 5px 7px; min-height: 30px; width: 100%; }
.bld-f input:disabled { opacity: .6; }
.bld-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.bld-row.tight { gap: 4px; }
.bld-note { color: var(--dim); font-size: 12px; }
.bld-msg { padding: 7px 12px; border-radius: 8px; font-size: 12.5px; margin: 0 0 10px; }
.bld-msg.bad { background: var(--bad-soft); color: var(--bad); } .bld-msg.info { background: var(--accent-soft); } .bld-msg.good { background: var(--good-soft); color: var(--good); }
.bld-tbl { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.bld-tbl td, .bld-tbl th { padding: 4px 6px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: middle; }
.bld-tbl input, .bld-tbl select { font: inherit; color: var(--ink); background: var(--bg); border: 1px solid var(--line); border-radius: 5px; padding: 3px 5px; min-height: 28px; width: 100%; min-width: 60px; }
.bld-pre { font-family: var(--mono); font-size: 11.5px; background: var(--surface2); border-radius: 6px; padding: 6px 8px; white-space: pre-wrap; overflow-wrap: anywhere; margin: 4px 0; }
.bld-pre .add { color: var(--good); } .bld-pre .del { color: var(--bad); }
.bld-two { display: grid; grid-template-columns: minmax(280px, 380px) 1fr; gap: 16px; align-items: start; }
.bld-svg { width: 100%; height: 360px; background: var(--canvas); border: 1px solid var(--line); border-radius: 8px; touch-action: none; }
.bld-svg .ol { fill: var(--substrate); stroke: var(--outline); stroke-width: 0.5px; vector-effect: non-scaling-stroke; }
.bld-svg .hd { fill: var(--accent); stroke: #fff; stroke-width: 1px; vector-effect: non-scaling-stroke; cursor: grab; }
.bld-svg .hd.sel { fill: var(--sel); }
.bld-svg .hole { fill: var(--canvas); stroke: var(--outline); stroke-width: 1px; vector-effect: non-scaling-stroke; }
.bld-svg .grd { stroke: var(--grid-minor); stroke-width: 1px; vector-effect: non-scaling-stroke; }
.bld-svg text { font-size: 3px; fill: var(--dim); }
@media (max-width: 900px) { .bld-two { grid-template-columns: 1fr; } #bld .bb { padding: 10px; } .bld-svg { height: 280px; } }
/* the Build tab */
#tab-build { padding: 0 0 24px; }
#tab-build .bt-head { padding: 8px 12px; border-bottom: 1px solid var(--line); display: grid; gap: 6px; }
#tab-build .bt-sec { padding: 8px 12px; border-bottom: 1px solid var(--line); }
#tab-build .bt-sec h3 { margin: 0 0 6px; font-size: 12.5px; color: var(--dim); text-transform: none; }
.bt-prow { display: grid; grid-template-columns: 22px minmax(0, 1.2fr) minmax(0, 1fr) auto; gap: 6px; padding: 5px 12px; border-bottom: 1px solid var(--line); align-items: center; cursor: pointer; font-size: 12.5px; }
.bt-prow:hover { background: var(--hover); } .bt-prow.sel { background: var(--accent-soft); } .bt-prow.tgt { outline: 2px solid var(--sel); outline-offset: -2px; }
.bt-prow .sub { color: var(--dim); font-size: 11.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bt-prow .sh { font-size: 11px; color: var(--warn); }
.bt-prow.nowrap > * { min-width: 0; }
.bt-chips { display: flex; gap: 4px; flex-wrap: wrap; }
.bt-chips button, .bt-side button { border: 1px solid var(--line); background: var(--surface2); border-radius: 999px; padding: 3px 11px; min-height: 28px; font-size: 12px; }
.bt-chips button.on, .bt-side button.on { background: var(--accent); color: #fff; border-color: var(--accent); }
.bt-offer { border: 1px solid var(--line); border-radius: 8px; padding: 6px 8px; margin: 6px 0; }
.bt-offer.need { opacity: .8; }
.bt-tray { display: flex; flex-wrap: wrap; gap: 4px; align-items: flex-end; }
.bt-tray div { border: 1px solid var(--line); background: var(--surface2); border-radius: 3px; font-size: 9px; color: var(--dim); overflow: hidden; line-height: 1.1; cursor: pointer; padding: 1px 2px; }
.bt-tray div.sel { border-color: var(--accent); background: var(--accent-soft); }
.bt-tl { display: grid; grid-template-columns: auto 1fr auto; gap: 8px; font-size: 12px; padding: 4px 0; border-bottom: 1px solid var(--line); cursor: pointer; }
.bt-turn { display: flex; gap: 6px; flex-wrap: wrap; }
.bt-turn button { border: 1px solid var(--line); background: var(--surface2); border-radius: 8px; padding: 4px 9px; font-size: 12px; }
.bt-turn button.best { border-color: var(--good); background: var(--good-soft); }
body[data-nv="build"] #tab-build { display: block; flex: 1 1 auto; }
body.bld-picking #board { cursor: crosshair; }
.bld-gate { border-left: 3px solid var(--warn); background: var(--warn-soft); padding: 6px 10px; border-radius: 6px; font-size: 12.5px; }
.bld-gate.open { border-color: var(--good); background: var(--good-soft); }
#buildbtn { margin-left: 4px; }
`;
document.head.appendChild(css);

// ---------------------------------------------------------------- the elements this adds
const wiz = document.createElement("div");
wiz.id = "bld"; wiz.hidden = true;
document.body.appendChild(wiz);
const tabBtn = document.createElement("button");
tabBtn.dataset.tab = "build"; tabBtn.id = "buildtab"; tabBtn.hidden = true; tabBtn.innerHTML = 'Build<em data-count="build"></em>';
q(".tabs").appendChild(tabBtn);
const nBtn = document.createElement("button");
nBtn.dataset.nv = "build"; nBtn.hidden = true; nBtn.innerHTML = "Build";
q("#ntabs").appendChild(nBtn);
const tabPane = document.createElement("div");
tabPane.className = "tab"; tabPane.id = "tab-build";
q("#side").appendChild(tabPane);
tabBtn.onclick = () => { goTab("build"); drawTab(); };
nBtn.onclick = () => { showNarrow("build"); drawTab(); };

// ---------------------------------------------------------------- state from the server
async function refreshState(reinit) {
  try { BS.st = await get("/build/state"); } catch (e) { return fail(e); }
  if (BS.st.phase === "ready" && BS.st.session) await refreshFacts(reinit);
  drawAll();
}
async function refreshFacts(reinit) {
  try { BS.facts = await get("/build/facts" + Object.keys(BS.acks).filter(k => BS.acks[k]).map((k, i) => (i ? "&" : "?") + "ack_" + encodeURIComponent(k) + "=1").join("")); }
  catch (e) { BS.facts = null; }
  if (reinit || !BS.form) initForm();             // what the user is typing is kept; a write reads the forms from the files again
}
async function refreshParts() {
  if (!BS.st || BS.st.phase !== "ready" || !BS.st.session || !BS.st.session.exists || !hasScript()) { BS.parts = null; return; }
  try { BS.parts = await get("/build/parts"); } catch (e) { BS.parts = null; fail(e); }
  drawTab();
}
const hasScript = () => !!(S.hello && !S.hello.picker && S.hello.script);
const gateOpen = () => !!(BS.facts && BS.facts.model.gate.open);

// ---------------------------------------------------------------- the start view
const _renderPicker = renderPicker;
renderPicker = function () {
  _renderPicker();
  const el = q("#picker");
  if (!S.hello || !S.hello.picker || !el) return;
  const list = (S.hello.builder && S.hello.builder.unbuilt) || [];
  let box = q(".box", el);
  if (!box) { el.innerHTML = '<div class="box"></div>'; box = q(".box", el); }
  const old = q("#bld-unbuilt", box);
  if (old) old.remove();
  if (!list.length) return;
  const g = document.createElement("div");
  g.id = "bld-unbuilt";
  g.innerHTML = "<h2>Boards with no layout</h2><p>A <code>.zen</code> that declares a board and has no <code>&lt;Board&gt;_layout.py</code> beside it. Pick one to build its layout script here.</p>" +
    list.map(u => '<button class="pick" data-build="' + h(u.id) + '"><b>' + h(u.name) + '</b><span class="sub">' + h(u.zen) + "</span></button>").join("");
  box.appendChild(g);
  g.onclick = e => { const b = e.target.closest("[data-build]"); if (b) startBoard(b.dataset.build); };
};
async function startBoard(id) {
  BS.closed = false; BS.facts = null; BS.form = null; BS.ol = null; BS.step = "board"; BS.acks = {};
  try { await post("/build/start", {id}); } catch (e) { return fail(e); }
  await refreshState();
}

// ---------------------------------------------------------------- the flow for a new board (full screen)
function drawAll() { drawWizard(); drawTab(); drawButtons(); }
function drawButtons() {
  const on = hasScript();
  tabBtn.hidden = !on; nBtn.hidden = !on;
}
// a script that exists is opened in the builder on demand: the board is generated (or restored from its cache) and read
async function openSession() {
  try { await post("/build/start", {current: true}); } catch (e) { return fail(e); }
  await refreshState();
}
function drawMsg() { const m = q("#bld-msg"); if (m) m.innerHTML = BS.msg ? '<div class="bld-msg ' + BS.msg.kind + '">' + h(BS.msg.text) + "</div>" : ""; const t = q("#bt-msg"); if (t) t.innerHTML = BS.msg ? '<div class="bld-msg ' + BS.msg.kind + '">' + h(BS.msg.text) + "</div>" : ""; }

let wizKey = "";
function drawWizard(force) {
  const st = BS.st;
  const sess = st && st.session;
  const show = !!(sess && !sess.exists && !BS.closed && S.hello && S.hello.picker);
  if (!show) { if (!BS.overlayFacts) wiz.hidden = true; wizKey = ""; return; }
  wiz.hidden = false; BS.overlayFacts = false;
  // what the user is typing in is not redrawn under them: only a change of step, phase or the log, or a request, draws it again
  const key = [BS.step, st.phase, sess.name, S.applied.length, !!S.redo, st.phase === "working" ? st.text : ""].join("|");
  if (!force && key === wizKey) return;
  wizKey = key;
  const steps = [["board", "1 Board"], ["facts", "2 Facts"], ["outline", "3 Outline"]];
  const gate = BS.facts ? BS.facts.model : null;
  wiz.innerHTML = '<div class="bh"><b>New layout: ' + h(sess.name) + '</b><span class="bld-note">' + h(sess.zen) + '</span><div class="steps">' +
    steps.map(s => '<button data-step="' + s[0] + '" class="' + (BS.step === s[0] ? "on" : "") + '">' + s[1] + "</button>").join("") + '</div><span style="flex:1"></span>' +
    '<button class="bld-btn" id="bld-undo"' + (S.applied.some(a => !a.undone) ? "" : " disabled") + '>Undo</button><button class="bld-btn" id="bld-redo"' + (S.redo ? "" : " disabled") + '>Redo</button>' +
    '<button class="bld-btn" id="bld-close">Close</button></div><div class="bb"><div class="bld-wrap"><div id="bld-msg"></div><div id="bld-body"></div></div></div>';
  q("#bld-close").onclick = () => { BS.closed = true; drawAll(); };
  q("#bld-undo").onclick = undo; q("#bld-redo").onclick = redo;
  qa("[data-step]", wiz).forEach(b => b.onclick = () => { BS.step = b.dataset.step; drawWizard(true); });
  drawMsg();
  const body = q("#bld-body");
  if (BS.step === "board") boardStep(body);
  else if (BS.step === "facts") factsStep(body);
  else outlineStep(body);
}

function boardStep(body) {
  const st = BS.st;
  if (st.phase === "working" || st.phase === "idle") {
    body.innerHTML = '<div class="bld-card"><h3>Reading the board</h3><div class="row"><i class="spin"></i> <span id="bld-prog">' + h(st.text || "starting") + "</span></div></div>";
    return;
  }
  if (st.phase === "error") {
    body.innerHTML = '<div class="bld-card"><h3>The board could not be read</h3><div class="bld-msg bad">' + h(st.text) + "</div>" +
      (st.tail ? '<div class="bld-pre">' + h(st.tail) + "</div>" : "") + '<button class="bld-btn" id="bld-retry">Try again</button></div>';
    q("#bld-retry").onclick = async () => { try { await post("/build/reload", {fresh: true}); } catch (e) { fail(e); } };
    return;
  }
  const b = st.board;
  body.innerHTML = '<div class="bld-card"><h3>The generated board</h3><div class="bld-grid">' +
    [["parts", b.parts], ["cells", b.cells], ["copper layers", b.copper_layers], ["courtyard area", b.total_courtyard_area.toFixed(1) + " mm²"]]
      .map(x => '<div class="bld-f"><span>' + x[0] + "</span><b>" + h(x[1]) + "</b></div>").join("") + '</div><p class="bld-note">Every footprint is unplaced: nothing is declared yet. State the board\'s facts next; nothing proceeds on a default.</p>' +
    '<button class="bld-btn primary" id="bld-next">Facts</button></div>';
  q("#bld-next").onclick = () => { BS.step = "facts"; drawWizard(true); };
}

// ---------------------------------------------------------------- facts
function initForm() {
  const f = BS.facts;
  if (!f) { BS.form = null; return; }
  const zr = f.zen.rows, layers = f.model.rows.filter(r => r.fact === "layer");
  const n = f.zen.copper_layers || layers.length || f.copper_layers;
  let rows = [];
  if (zr && zr.length) rows = zr.map(r => r.kind === "copper" ? {kind: "copper", role: r.role, mode: r.oz ? "oz" : "um", val: r.oz ? String(r.oz) : String(Math.round(r.thickness_mm * 1000 * 100) / 100)} :
    {kind: "dielectric", mm: String(r.thickness_mm), form: r.form || ""});
  else for (let i = 0; i < n; i++) { rows.push({kind: "copper", role: "", mode: "oz", val: ""}); if (i < n - 1) rows.push({kind: "dielectric", mm: "", form: ""}); }
  const cls = (f.zen.classes || []).map(c => ({on: true, name: c.name, w: String(c.diff_pair_width), g: String(c.diff_pair_gap), nets: c.nets || []}));
  for (const c of f.candidates) if (!cls.some(x => x.nets.includes(c.positive))) cls.push({on: false, name: c.base, w: "", g: "", nets: [c.positive, c.negative]});
  const prof = f.fab.profile || {}, via = prof.via || {}, mn = prof.min || {};
  BS.form = {
    n, rows, classes: cls, none: !!BS.acks.no_pairs,
    via: {micro: via.micro || "", blind: via.blind || "", buried: via.buried || "", drill: via.default_drill_mm != null ? String(via.default_drill_mm) : "", size: via.default_size_mm != null ? String(via.default_size_mm) : ""},
    min: Object.fromEntries(f.defaults.min_keys.map(k => [k, mn[k] != null ? String(mn[k]) : ""])),
    rise: f.rise.set ? String(f.rise.value) : "", result: BS.form && BS.form.result,
  };
}
const num = v => { const x = parseFloat(v); return isFinite(x) ? x : null; };
const stateChip = s => '<span class="chip ' + (s === "decided" ? "good" : s === "undecided" ? "bad" : "warn") + '">' + h(s) + "</span>";

function factsStep(body) {
  if (!BS.facts || !BS.form) { body.innerHTML = '<div class="bld-card">Reading the facts ...</div>'; if (BS.st && BS.st.phase === "ready") refreshFacts().then(() => drawWizard(true)); return; }
  body.innerHTML = '<div id="bld-facts-top"></div><div class="bld-card" id="bld-stack"></div><div class="bld-card" id="bld-pairs"></div><div class="bld-card" id="bld-vias"></div><div class="bld-card" id="bld-rise"></div><div id="bld-facts-bot"></div>';
  drawFactsTop(); stackCard(); pairsCard(); viasCard(); riseCard(); drawFactsBottom();
}
function drawFactsTop() {
  const m = BS.facts.model, c = m.counts;
  q("#bld-facts-top").innerHTML = '<div class="bld-card"><h3>Facts <span class="bld-note">' + h(c.undecided + " undecided, " + c.flagged + " flagged, " + c.changed + " changed, " + c.decided + " decided") + '</span></h3>' +
    '<div class="bld-row tight">' + m.rows.map(r => '<span title="' + h(r.home) + '">' + h(r.label) + " " + stateChip(r.state) + "</span>").join(" &nbsp; ") + "</div>" +
    (m.reasons.length ? '<h4>Why it is unconfirmed</h4>' + m.reasons.map(r => '<div class="bld-note">' + h(r.text) + "</div>").join("") : "") + "</div>";
}
function sectionState(ids) { const rs = BS.facts.model.rows.filter(r => ids(r)); return rs.length ? stateChip(rs.some(r => r.state === "undecided") ? "undecided" : rs.some(r => r.state === "changed") ? "changed" : "decided") : ""; }

function stackCard() {
  const f = BS.facts, F = BS.form, z = f.zen, el = q("#bld-stack");
  if (!z.editable) { el.innerHTML = "<h3>Layer roles and copper weights</h3><div class=\"bld-msg info\">" + h(z.stackup === "elsewhere" ? "The stackup is declared where the builder does not edit it (" + z.why + "): change it in the file. Its values are read from the board." : "The .zen cannot be read: " + z.why) + "</div>"; return; }
  const cu = F.rows.filter(r => r.kind === "copper").length;
  el.innerHTML = "<h3>Layer roles and copper weights " + sectionState(r => r.fact === "layer") + '</h3><p class="bld-note">Declared in <code>' + h(z.file) + '</code> as <code>Board(config=BoardConfig(stackup=Stackup(layers=[...])))</code>. ' +
    (f.model.rows.some(r => r.fact === "layer" && r.default) ? "The board has the generator's default stackup: nobody declared one, so each layer is undecided." : "") + '</p>' +
    '<div class="bld-row"><label class="bld-f" style="width:160px">Copper layers<input type="number" min="1" max="32" step="1" id="st-n" value="' + cu + '"></label></div>' +
    '<table class="bld-tbl"><tr><th>Layer</th><th>Role / form</th><th>Weight or thickness</th><th></th></tr>' +
    F.rows.map((r, i) => r.kind === "copper" ? '<tr><td>' + h(layerName(i)) + '</td><td><select data-st="' + i + '" data-k="role"><option value="">choose</option>' + ["signal", "power", "mixed", "ground"].map(x => '<option' + (r.role === x ? " selected" : "") + ">" + x + "</option>").join("") + '</select></td><td><div class="bld-row tight"><input data-st="' + i + '" data-k="val" value="' + h(r.val) + '" style="max-width:90px"><select data-st="' + i + '" data-k="mode" style="max-width:80px">' + ["oz", "um", "mm"].map(x => '<option' + (r.mode === x ? " selected" : "") + ">" + x + "</option>").join("") + '</select><span class="bld-note" id="st-conv-' + i + '">' + h(convText(r)) + "</span></div></td><td></td></tr>" :
      '<tr><td class="bld-note">dielectric</td><td><select data-st="' + i + '" data-k="form"><option value="">any</option>' + ["core", "prepreg"].map(x => '<option' + (r.form === x ? " selected" : "") + ">" + x + "</option>").join("") + '</select></td><td><div class="bld-row tight"><input data-st="' + i + '" data-k="mm" value="' + h(r.mm) + '" style="max-width:90px"><span class="bld-note">mm</span></div></td><td></td></tr>').join("") +
    '</table><div class="bld-row" style="margin-top:8px"><button class="bld-btn primary" id="st-write">Write the stackup</button><span class="bld-note">1 oz/ft² = 0.035 mm; the file holds the thickness in mm with the oz as a comment.</span></div>';
  q("#st-n").onchange = e => resizeStack(parseInt(e.target.value, 10));
  qa("[data-st]", el).forEach(inp => inp.oninput = inp.onchange = e => { const r = F.rows[+inp.dataset.st]; r[inp.dataset.k] = inp.value; const c = q("#st-conv-" + inp.dataset.st); if (c) c.textContent = convText(r); });
  q("#st-write").onclick = () => writeFacts("stackup");
}
function layerName(i) { const cu = BS.form.rows.map((r, k) => r.kind === "copper" ? k : -1).filter(k => k >= 0), n = cu.indexOf(i); return n === 0 ? "F.Cu" : n === cu.length - 1 ? "B.Cu" : "In" + n + ".Cu"; }
function convText(r) {
  const v = num(r.val); if (v == null) return "";
  if (r.mode === "oz") return "= " + (Math.round(v * OZ_MM * 10000) / 10000) + " mm";
  const mm = r.mode === "um" ? v / 1000 : v, oz = mm / OZ_MM;
  return "= " + (Math.round(oz * 100) / 100) + " oz";
}
function resizeStack(n) {
  if (!(n >= 1)) return;
  const F = BS.form, cu = F.rows.filter(r => r.kind === "copper");
  const rows = [];
  for (let i = 0; i < n; i++) { rows.push(cu[i] || {kind: "copper", role: "", mode: "oz", val: ""}); if (i < n - 1) rows.push({kind: "dielectric", mm: "", form: ""}); }
  F.rows = rows; stackCard();
}
function pairsCard() {
  const F = BS.form, f = BS.facts, el = q("#bld-pairs");
  if (!f.zen.editable) { el.innerHTML = "<h3>Differential pairs</h3><div class=\"bld-msg info\">Declared where the builder does not edit it.</div>"; return; }
  el.innerHTML = "<h3>Differential pairs " + sectionState(r => r.fact === "pairs") + '</h3><p class="bld-note">One <code>NetClass</code> per pair with exactly its two nets, in <code>design_rules.netclasses</code> of <code>' + h(f.zen.file) + '</code>. Candidates are suggestions from the net names.</p>' +
    '<label class="bld-row"><input type="checkbox" id="pr-none"' + (F.none ? " checked" : "") + '> this board has no differential pairs</label>' +
    '<table class="bld-tbl"><tr><th></th><th>Class</th><th>Nets</th><th>Width mm</th><th>Gap mm</th></tr>' +
    F.classes.map((c, i) => '<tr><td><input type="checkbox" data-pr="' + i + '" data-k="on"' + (c.on ? " checked" : "") + '></td><td><input data-pr="' + i + '" data-k="name" value="' + h(c.name) + '"></td><td>' + h(c.nets.join(" / ")) + '</td><td><input data-pr="' + i + '" data-k="w" value="' + h(c.w) + '"></td><td><input data-pr="' + i + '" data-k="g" value="' + h(c.g) + '"></td></tr>').join("") + "</table>" +
    '<div class="bld-row" style="margin-top:6px"><select id="pr-a" class="bld-in" style="max-width:200px">' + f.nets.map(n => "<option>" + h(n) + "</option>").join("") + '</select><select id="pr-b" class="bld-in" style="max-width:200px">' + f.nets.map(n => "<option>" + h(n) + "</option>").join("") + '</select><button class="bld-btn" id="pr-add">Add this pair</button></div>' +
    '<div class="bld-row" style="margin-top:8px"><button class="bld-btn primary" id="pr-write">Write the pair classes</button></div>';
  q("#pr-none").onchange = e => { F.none = e.target.checked; BS.acks.no_pairs = F.none; };
  qa("[data-pr]", el).forEach(inp => inp.oninput = inp.onchange = () => { const c = F.classes[+inp.dataset.pr]; c[inp.dataset.k] = inp.dataset.k === "on" ? inp.checked : inp.value; });
  q("#pr-add").onclick = () => { const a = q("#pr-a").value, b = q("#pr-b").value; if (a === b) return say("A pair is two different nets.", "bad"); F.classes.push({on: true, name: a.replace(/[_+-][PN]?$/i, "") || a, w: "", g: "", nets: [a, b]}); pairsCard(); };
  q("#pr-write").onclick = () => writeFacts("pairs");
}
function viasCard() {
  const F = BS.form, f = BS.facts, el = q("#bld-vias");
  const file = f.fab.file || "fab-profile.json";
  const tier = k => '<label class="bld-f">' + k + ' vias<select data-vi="' + k + '"><option value="">choose</option>' + f.defaults.tiers.map(t => '<option' + (F.via[k] === t ? " selected" : "") + ">" + t + "</option>").join("") + "</select></label>";
  el.innerHTML = "<h3>Via types and fab minimums " + sectionState(r => r.fact === "via" || r.fact === "min") + '</h3><p class="bld-note">In <code>' + h(file) + "</code>. " + h(f.fab.says) + '</p><div class="bld-grid">' +
    f.defaults.via_kinds.map(tier).join("") +
    '<label class="bld-f">default drill mm<input data-vi="drill" value="' + h(F.via.drill) + '"></label><label class="bld-f">default size mm<input data-vi="size" value="' + h(F.via.size) + '"></label></div><h4>Fab minimums (mm)</h4><div class="bld-grid">' +
    f.defaults.min_keys.map(k => '<label class="bld-f">' + h(k.replace("_mm", "")) + '<input data-mn="' + k + '" value="' + h(F.min[k]) + '"></label>').join("") + '</div>' +
    '<div class="bld-row" style="margin-top:8px"><button class="bld-btn primary" id="vi-write">Write via types and minimums</button></div>';
  qa("[data-vi]", el).forEach(inp => inp.oninput = inp.onchange = () => { F.via[inp.dataset.vi] = inp.value; });
  qa("[data-mn]", el).forEach(inp => inp.oninput = () => { F.min[inp.dataset.mn] = inp.value; });
  q("#vi-write").onclick = () => writeFacts("via");
}
function riseCard() {
  const F = BS.form, f = BS.facts, el = q("#bld-rise");
  el.innerHTML = "<h3>The rise " + sectionState(r => r.fact === "rise") + '</h3><p class="bld-note">The temperature rise the current checks allow, in <code>placemat.toml</code> <code>[check] rise_c</code>.</p><div class="bld-row"><label class="bld-f" style="width:140px">degrees C<input id="rs-v" value="' + h(F.rise) + '"></label>' +
    '<button class="bld-btn primary" id="rs-write">Write the rise</button><button class="bld-btn" id="rs-def">Use the default, ' + h(f.rise.value) + " C</button></div>";
  q("#rs-v").oninput = e => { F.rise = e.target.value; };
  q("#rs-write").onclick = () => writeFacts("rise");
  q("#rs-def").onclick = () => { F.rise = String(f.rise.value); q("#rs-v").value = F.rise; writeFacts("rise"); };
}
function factsRequest(which) {
  const F = BS.form, req = {};
  if (which === "stackup") {
    const rows = [];
    for (const r of F.rows) {
      if (r.kind === "copper") {
        if (!r.role) throw new Error("choose each copper layer's role");
        const v = num(r.val);
        if (v == null || v <= 0) throw new Error("give each copper layer its weight or thickness");
        rows.push(r.mode === "oz" ? {kind: "copper", role: r.role, oz: v} : r.mode === "um" ? {kind: "copper", role: r.role, thickness_um: v} : {kind: "copper", role: r.role, thickness_mm: v});
      } else {
        const v = num(r.mm); if (v == null || v <= 0) throw new Error("give each dielectric its thickness in mm");
        rows.push({kind: "dielectric", thickness_mm: v, form: r.form || null});
      }
    }
    req.stackup = {copper_layers: F.rows.filter(r => r.kind === "copper").length, rows};
  } else if (which === "pairs") {
    const on = F.classes.filter(c => c.on);
    if (!on.length && !F.none) throw new Error("tick a pair, or say this board has no differential pairs");
    req.pairs = {classes: on.map(c => { const w = num(c.w), g = num(c.g); if (!c.name || w == null || g == null) throw new Error("give each pair a class name, a width and a gap in mm"); return {name: c.name, diff_pair_width: w, diff_pair_gap: g, nets: c.nets}; })};
  } else if (which === "via") {
    const v = {};
    for (const k of ["micro", "blind", "buried"]) { if (!F.via[k]) throw new Error("choose a tier for " + k + " vias (no is a decision)"); v[k] = F.via[k]; }
    if (num(F.via.drill) != null) v.default_drill_mm = num(F.via.drill);
    if (num(F.via.size) != null) v.default_size_mm = num(F.via.size);
    req.via = v;
    const mn = {};
    for (const [k, s] of Object.entries(F.min)) if (num(s) != null) mn[k] = num(s);
    if (!Object.keys(mn).length) throw new Error("give the fab's minimums (at least one)");
    req.min = mn;
  } else if (which === "rise") {
    const v = num(F.rise); if (v == null || v <= 0) throw new Error("the rise is a number of degrees C above 0");
    req.rise_c = v;
  }
  return req;
}
async function writeFacts(which) {
  let req;
  try { req = factsRequest(which); } catch (e) { return say(e.message, "bad"); }
  if (hasScript() && BS.parts && BS.parts.counts && (BS.parts.counts.decided || BS.parts.counts.searched) && !confirm("Changing a fact regenerates the board and re-resolves the placements. Go on?")) return;
  say("Writing and regenerating ...", "info");
  try {
    const out = await post("/build/facts/apply", {request: req});
    BS.form.result = out;
    say(out.readback && out.readback.length ? "Written, but the generated board did not take " + out.readback.map(r => r.name).join(", ") + ". Undo is offered." : "Written to " + out.files.join(", ") + (out.says && out.says.length ? ". " + out.says.join(" ") : "") + ".", out.readback && out.readback.length ? "bad" : "good");
  } catch (e) { return fail(e); }
  await refreshState(true);
  redrawFacts();
}
// the facts are drawn in the new-board flow, or, for a script that exists, in an overlay over the page: draw whichever is showing
function redrawFacts() {
  if (!BS.st || !BS.st.session) return;
  if (BS.st.session.exists) { if (BS.overlayFacts) factsOverlay(); } else drawWizard(true);
}
function drawFactsBottom() {
  const f = BS.facts, m = f.model, el = q("#bld-facts-bot");
  const flagged = m.rows.filter(r => r.fact === "layer" && r.flag);
  const res = BS.form.result;
  el.innerHTML = '<div class="bld-card"><h3>Confirm</h3>' +
    (res && res.readback && res.readback.length ? '<div class="bld-msg bad">The generator did not take: ' + res.readback.map(r => h(r.name + " (asked " + JSON.stringify(r.asked) + ", got " + JSON.stringify(r.got) + ")")).join("; ") + '. <button class="bld-btn" id="fb-undo">Undo the batch</button></div>' : "") +
    flagged.map(r => '<label class="bld-row"><input type="checkbox" data-ack="plane:' + h(r.label) + '"' + (BS.acks["plane:" + r.label] ? " checked" : "") + '> ' + h(r.flag) + ": the plane is declared in the layout script, not here (acknowledge it, or change the layer's role above)</label>").join("") +
    '<div class="bld-gate' + (m.gate.open ? " open" : "") + '">' + (m.gate.open ? "The facts are confirmed: placement is open." : "Placement and \"Search the rest\" wait for this confirmation. " + h(m.confirmable.join("; "))) + '</div>' +
    '<div class="bld-row" style="margin-top:8px"><button class="bld-btn primary" id="fb-confirm"' + (m.confirmable.length ? " disabled" : "") + ">Confirm the facts</button></div></div>";
  qa("[data-ack]", el).forEach(i => i.onchange = async () => { BS.acks[i.dataset.ack] = i.checked; await refreshFacts(); redrawFacts(); });
  const ub = q("#fb-undo"); if (ub) ub.onclick = undo;
  q("#fb-confirm").onclick = async () => {
    try { const out = await post("/build/facts/confirm", {acks: BS.acks}); say("Confirmed in " + out.file + ".", "good"); } catch (e) { return fail(e); }
    await refreshState(); await refreshParts(); redrawFacts();
  };
}

// ---------------------------------------------------------------- undo and redo (the applied log)
async function undo() { try { await post("/suggest/undo"); say("Undone.", "info"); } catch (e) { fail(e); } await afterWrite(); }
async function redo() { try { await post("/suggest/redo"); say("Redone.", "info"); } catch (e) { fail(e); } await afterWrite(); }
async function afterWrite() { await refreshState(); await refreshParts(); }

// ---------------------------------------------------------------- the outline
const SHAPE_LABEL = {rect: "Rectangle", rect_chamfer: "Rectangle, corners cut", rect_round: "Rectangle, corners rounded", disc: "Circle", disc_bore: "Circle with a bore", slot: "Slot (a stadium)", polygon: "Polygon"};
const TEMPLATES = {"": "Free vertex list", l_shape: "L shape", notch: "Notched edge", cut_corners: "Cut corners"};
function newOutline(from) {
  const st = BS.st || {}, set = st.settings || {fill: 0.5};
  const o = {shape: "rect", w: "", h: "", ch: "2", ra: "2", d: "", bore: "6", len: "", wid: "", points: [[0, 0], [60, 0], [60, 25], [35, 25], [35, 40], [0, 40]], template: "", faces: 1,
    fill: String(set.max_fill != null ? set.max_fill * 100 : 50), aspect: String(set.aspect || 1), typed: false, holes: [], web: "1", desc: "", sug: null, fillShown: null, sel: -1, existing: !!from, choices: {}};
  if (from && from.outline) {
    const ol = from.outline, d = ol.dims || {};
    Object.assign(o, {shape: ol.shape === "other" ? "rect" : ol.shape, typed: true});
    if (d.width != null) o.w = String(d.width); if (d.height != null) o.h = String(d.height); if (d.diameter != null) o.d = String(d.diameter);
    if (d.length != null) o.len = String(d.length); if (d.chamfer != null) o.ch = String(d.chamfer); if (d.radius != null) o.ra = String(d.radius);
    if (d.bore != null) o.bore = String(d.bore); if (d.web != null) o.web = String(d.web);
    if (ol.shape === "slot") o.wid = String(d.width || ""), o.w = "";
    if (ol.points) o.points = ol.points;
    o.readOnly = ol.editable === false ? ol.why : "";
  }
  return o;
}
const isRect = s => s.startsWith("rect"), isDisc = s => s.startsWith("disc");
function olSpec(o) {
  const n = num, s = {shape: o.shape};
  if (isRect(o.shape)) { s.width = n(o.w); s.height = n(o.h); if (o.shape === "rect_chamfer") s.chamfer = n(o.ch); if (o.shape === "rect_round") s.radius = n(o.ra); }
  else if (isDisc(o.shape)) { s.diameter = n(o.d); if (o.shape === "disc_bore") s.bore = n(o.bore); }
  else if (o.shape === "slot") { s.length = n(o.len); s.width = n(o.wid); }
  else s.points = o.points;
  if (o.existing) {
    s.add_holes = o.holes.map(x => ({name: x.name, kind: x.kind, diameter: n(x.dia), length: n(x.hlen), width: n(x.hwid), at: x.at === "edge" ? {edge: x.edge, along: "MID"} : {bearing: x.bearing, radius: n(x.rad)}}));
    if (!s.add_holes.length) delete s.add_holes;
    if ((o.removeHoles || []).length) s.remove_holes = o.removeHoles;
    if (o.holes.some(x => x.at === "edge")) s.web = n(o.web);
  } else if (o.holes.length) {
    s.holes = o.holes.map(x => ({name: x.name, kind: x.kind, diameter: n(x.dia), length: n(x.hlen), width: n(x.hwid), at: x.at === "edge" ? {edge: x.edge, along: "MID"} : {bearing: x.bearing, radius: n(x.rad)}}));
    if (o.holes.some(x => x.at === "edge")) s.web = n(o.web);
  }
  if (!o.typed && o.sug && o.shape !== "polygon") s.origin = {mode: "suggested", faces: +o.faces, fill: n(o.fill) / 100, aspect: n(o.aspect)};
  if (!o.typed && o.sug && o.shape === "polygon" && o.template) s.origin = {mode: "suggested", faces: +o.faces, fill: n(o.fill) / 100, aspect: n(o.aspect)};
  return s;
}
let sugTimer = null;
function askSuggestion() {
  const o = BS.ol; if (!o || !BS.st || BS.st.phase !== "ready") return;
  clearTimeout(sugTimer);
  sugTimer = setTimeout(async () => {
    const req = {shape: o.shape, faces: +o.faces, fill: num(o.fill) / 100, aspect: num(o.aspect), template: o.template || undefined, slot_aspect: num(o.len) && num(o.wid) ? num(o.len) / num(o.wid) : undefined};
    try {
      if (o.typed) {
        const spec = olSpec(o);
        if (o.shape === "polygon" ? o.points.length >= 3 : Object.values(spec).every(v => v !== null)) {
          const typed = Object.fromEntries(Object.entries(spec).filter(([k]) => !["shape", "holes", "web", "origin"].includes(k)));
          const r = await post("/build/outline/suggest", {shape: o.shape, faces: +o.faces, typed});
          o.fillShown = r.fill;
        }
      } else {
        const r = await post("/build/outline/suggest", req);
        o.sug = r;
        if (isRect(o.shape)) { o.w = String(r.width); o.h = String(r.height); }
        else if (isDisc(o.shape)) o.d = String(r.diameter);
        else if (o.shape === "slot") { o.len = String(r.length); o.wid = String(r.width); }
        else if (r.points) o.points = r.points;
        o.fillShown = null;
      }
    } catch (e) { o.sug = null; o.fillShown = null; }
    drawOutlineValues();
  }, 120);
}
function outlineStep(body) {
  if (!BS.st || BS.st.phase !== "ready") { body.innerHTML = '<div class="bld-card">The board is not read yet.</div>'; return; }
  if (!BS.ol) { BS.ol = newOutline(null); askSuggestion(); }
  drawOutline(body, "create");
}
function drawOutline(body, mode) {
  BS.olBody = body;
  const o = BS.ol, b = BS.st.board, set = BS.st.settings || {};
  const f = (label, key, extra) => '<label class="bld-f">' + label + '<input data-ol="' + key + '" value="' + h(o[key]) + '" inputmode="decimal"' + (extra || "") + "></label>";
  body.innerHTML = '<div class="bld-two"><div class="bld-card"><h3>' + (mode === "create" ? "Outline" : "Change the outline") + '</h3>' +
    (o.readOnly ? '<div class="bld-msg bad">Read only: ' + h(o.readOnly) + "</div>" : "") +
    '<label class="bld-f">Shape<select data-ol="shape">' + Object.keys(SHAPE_LABEL).map(k => '<option value="' + k + '"' + (o.shape === k ? " selected" : "") + ">" + SHAPE_LABEL[k] + "</option>").join("") + "</select></label>" +
    (o.shape === "polygon" ? '<label class="bld-f">Template<select data-ol="template">' + Object.keys(TEMPLATES).map(k => '<option value="' + k + '"' + (o.template === k ? " selected" : "") + ">" + TEMPLATES[k] + "</option>").join("") + "</select></label>" : "") +
    '<h4>Suggested size</h4><div class="bld-grid"><label class="bld-f">Fill, % of a face<input data-ol="fill" value="' + h(o.fill) + '"></label><label class="bld-f">Faces<select data-ol="faces"><option value="1"' + (+o.faces === 1 ? " selected" : "") + '>one</option><option value="2"' + (+o.faces === 2 ? " selected" : "") + ">two</option></select></label>" +
    (isRect(o.shape) || o.template ? f("Aspect (width / height)", "aspect") : "") + '</div><div class="bld-note" id="ol-sug"></div><h4>Size, mm</h4><div class="bld-grid">' +
    (isRect(o.shape) ? f("Width", "w") + f("Height", "h") + (o.shape === "rect_chamfer" ? f("Chamfer", "ch") : "") + (o.shape === "rect_round" ? f("Corner radius", "ra") : "") : "") +
    (isDisc(o.shape) ? f("Diameter", "d") + (o.shape === "disc_bore" ? f("Bore", "bore") : "") : "") + (o.shape === "slot" ? f("Length", "len") + f("Width", "wid") : "") + '</div><div class="bld-note" id="ol-fill"></div>' +
    (o.shape === "polygon" ? '<h4>Vertices, mm from the top-left, y down</h4><div id="ol-pts"></div><button class="bld-btn" id="ol-addpt">Add a vertex</button> <button class="bld-btn" id="ol-delpt">Remove the selected</button>' : "") +
    '<h4>Holes</h4><div id="ol-holes"></div><button class="bld-btn" id="ol-addhole">Add a hole</button>' +
    (mode === "create" ? '<h4>The script</h4><label class="bld-f">Description (the script\'s docstring, optional)<input data-ol="desc" value="' + h(o.desc) + '"></label>' : "") +
    '<div class="bld-row" style="margin-top:12px"><button class="bld-btn primary" id="ol-go">' + (mode === "create" ? "Make the layout script" : "Apply the change") + '</button><span class="bld-note" id="ol-err"></span></div><div id="ol-aff"></div></div>' +
    '<div class="bld-card"><svg class="bld-svg" id="ol-svg" xmlns="http://www.w3.org/2000/svg"></svg><p class="bld-note">Drag a handle to change a size (it snaps to ' + h(set.grid_mm) + ' mm); the origin is the top-left corner and does not move. A drag is a size, never a position.</p>' +
    '<div class="bld-note">Parts: ' + h(b.total_courtyard_area.toFixed(1)) + " mm² of courtyard.</div></div></div>";
  qa("[data-ol]", body).forEach(inp => inp.onchange = inp.oninput = e => olInput(inp, e.type === "change"));
  q("#ol-go").onclick = () => olGo(mode);
  const ap = q("#ol-addpt"); if (ap) { ap.onclick = () => { o.points.push([0, 0]); o.sel = o.points.length - 1; o.typed = true; drawOutline(body, mode); }; q("#ol-delpt").onclick = () => { if (o.sel >= 0 && o.points.length > 3) { o.points.splice(o.sel, 1); o.sel = -1; o.typed = true; drawOutline(body, mode); } }; }
  q("#ol-addhole").onclick = () => { o.holes.push({name: "mount" + (o.holes.length ? o.holes.length + 1 : ""), kind: "circle", dia: "3.2", hlen: "8", hwid: "2", at: isDisc(o.shape) ? "polar" : "edge", edge: "NORTH", bearing: "EAST", rad: "15"}); drawOutline(body, mode); };
  o.mode = mode;
  drawOutlineValues(true);
}
function olInput(inp, committed) {
  const o = BS.ol, k = inp.dataset.ol, v = inp.value;
  o[k] = v;
  if (k === "shape" || k === "template") { o.typed = false; if (k === "shape" && o.sug) o.sug = null; drawOutline(BS.olBody, o.mode); askSuggestion(); return; }
  if (["fill", "faces", "aspect"].includes(k)) { o.typed = false; askSuggestion(); }
  else if (["w", "h", "d", "len", "wid", "ch", "ra", "bore"].includes(k)) { o.typed = true; askSuggestion(); }
  drawOutlineValues();
}
function drawOutlineValues(full) {
  const o = BS.ol; if (!o) return;
  const sug = q("#ol-sug"), fl = q("#ol-fill");
  if (sug) sug.textContent = o.typed ? "" : (o.sug ? "suggested from " + o.sug.total_area.toFixed(1) + " mm² of courtyard on " + (o.sug.faces === 2 ? "two faces" : "one face") + " at " + Math.round(o.sug.fill * 100) + "% fill: area " + o.sug.area.toFixed(1) + " mm²" : "");
  if (fl) fl.textContent = o.typed && o.fillShown != null ? "A typed size: the parts fill " + (o.fillShown * 100).toFixed(1) + "% of each face (read only; edit the fill field to return to the suggestion)." : "";
  if (!full) for (const k of ["w", "h", "d", "len", "wid"]) { const i = q('[data-ol="' + k + '"]'); if (i && document.activeElement !== i) i.value = o[k]; }
  const pts = q("#ol-pts");
  if (pts) pts.innerHTML = '<table class="bld-tbl">' + o.points.map((p, i) => '<tr class="' + (o.sel === i ? "sel" : "") + '"><td><input type="radio" name="olsel" data-sel="' + i + '"' + (o.sel === i ? " checked" : "") + '></td><td><input data-pt="' + i + '" data-c="0" value="' + p[0] + '"></td><td><input data-pt="' + i + '" data-c="1" value="' + p[1] + '"></td></tr>').join("") + "</table>";
  if (pts) { qa("[data-pt]", pts).forEach(inp => inp.oninput = () => { const v = num(inp.value); if (v != null) { o.points[+inp.dataset.pt][+inp.dataset.c] = v; o.typed = true; drawSvg(); } }); qa("[data-sel]", pts).forEach(r => r.onchange = () => { o.sel = +r.dataset.sel; drawSvg(); }); }
  drawHoles(); drawSvg();
}
function drawHoles() {
  const o = BS.ol, el = q("#ol-holes"); if (!el) return;
  const have = (o.existing && BS.parts && BS.parts.outline && BS.parts.outline.holes) || [];
  o.removeHoles = (o.removeHoles || []).filter(n => have.includes(n));
  el.innerHTML = (have.length ? '<div class="bld-note">Holes the script has: tick one to take it out (its constants go with it).</div>' + have.map(n => '<label class="bld-row"><input type="checkbox" data-rmh="' + h(n) + '"' + (o.removeHoles.includes(n) ? " checked" : "") + "> " + h(n) + "</label>").join("") : "") + o.holes.map((x, i) => '<div class="bld-card" style="margin:4px 0"><div class="bld-grid"><label class="bld-f">Name<input data-ho="' + i + '" data-k="name" value="' + h(x.name) + '"></label><label class="bld-f">Kind<select data-ho="' + i + '" data-k="kind"><option value="circle"' + (x.kind === "circle" ? " selected" : "") + '>round</option><option value="slot"' + (x.kind === "slot" ? " selected" : "") + ">slot</option></select></label>" +
    (x.kind === "circle" ? '<label class="bld-f">Diameter<input data-ho="' + i + '" data-k="dia" value="' + h(x.dia) + '"></label>' : '<label class="bld-f">Length<input data-ho="' + i + '" data-k="hlen" value="' + h(x.hlen) + '"></label><label class="bld-f">Width<input data-ho="' + i + '" data-k="hwid" value="' + h(x.hwid) + '"></label>') +
    (isDisc(o.shape) ? '<label class="bld-f">Bearing<select data-ho="' + i + '" data-k="bearing">' + SIDES.map(s => '<option' + (x.bearing === s ? " selected" : "") + ">" + s + "</option>").join("") + '</select></label><label class="bld-f">Radius from the middle<input data-ho="' + i + '" data-k="rad" value="' + h(x.rad) + '"></label>' :
      '<label class="bld-f">Middle of the edge<select data-ho="' + i + '" data-k="edge">' + SIDES.map(s => '<option' + (x.edge === s ? " selected" : "") + ">" + s + "</option>").join("") + "</select></label>") +
    '</div><button class="bld-btn" data-rm="' + i + '">Remove</button></div>').join("") +
    (o.holes.some(x => x.at === "edge") ? '<label class="bld-f" style="max-width:220px">Web: material kept round a hole, mm<input data-ol="web" value="' + h(o.web) + '"></label><div class="bld-note">A hole on an edge stands in from it by the web plus half its size. A hole at the start or end of an edge would reach past the corner, so edge holes are in the middle.</div>' : "");
  qa("[data-rmh]", el).forEach(c => c.onchange = () => { const n = c.dataset.rmh; o.removeHoles = (o.removeHoles || []).filter(x => x !== n); if (c.checked) o.removeHoles.push(n); });
  qa("[data-ho]", el).forEach(inp => inp.onchange = inp.oninput = () => { o.holes[+inp.dataset.ho][inp.dataset.k] = inp.value; if (inp.dataset.k === "kind") drawHoles(); });
  qa("[data-rm]", el).forEach(b => b.onclick = () => { o.holes.splice(+b.dataset.rm, 1); drawHoles(); drawSvg(); });
  const web = q('[data-ol="web"]', el); if (web) web.oninput = () => { o.web = web.value; };
}
// the preview: the outline in mm, with handles that change a size
function olBox(o) {
  if (isRect(o.shape)) return [num(o.w) || 60, num(o.h) || 40];
  if (isDisc(o.shape)) { const d = num(o.d) || 50; return [d, d]; }
  if (o.shape === "slot") return [num(o.len) || 60, num(o.wid) || 30];
  const xs = o.points.map(p => p[0]), ys = o.points.map(p => p[1]);
  return [Math.max(1, ...xs), Math.max(1, ...ys)];
}
function drawSvg() {
  const o = BS.ol, svg = q("#ol-svg"); if (!svg) return;
  const [w, hh] = olBox(o), pad = Math.max(w, hh) * 0.12, vb = [-pad, -pad, w + 2 * pad, hh + 2 * pad];
  svg.setAttribute("viewBox", vb.join(" "));
  const hs = Math.max(w, hh) * 0.018;
  let shape = "", handles = "";
  if (isRect(o.shape)) {
    const ch = o.shape === "rect_chamfer" ? num(o.ch) || 0 : 0, ra = o.shape === "rect_round" ? num(o.ra) || 0 : 0;
    shape = ch ? '<polygon class="ol" points="' + [[ch, 0], [w - ch, 0], [w, ch], [w, hh - ch], [w - ch, hh], [ch, hh], [0, hh - ch], [0, ch]].map(p => p.join(",")).join(" ") + '"/>' : '<rect class="ol" x="0" y="0" width="' + w + '" height="' + hh + '" rx="' + ra + '"/>';
    handles = '<circle class="hd" data-h="w" cx="' + w + '" cy="' + hh / 2 + '" r="' + hs + '"/><circle class="hd" data-h="h" cx="' + w / 2 + '" cy="' + hh + '" r="' + hs + '"/>';
  } else if (isDisc(o.shape)) {
    shape = '<circle class="ol" cx="' + w / 2 + '" cy="' + w / 2 + '" r="' + w / 2 + '"/>' + (o.shape === "disc_bore" ? '<circle class="hole" cx="' + w / 2 + '" cy="' + w / 2 + '" r="' + (num(o.bore) || 0) / 2 + '"/>' : "");
    handles = '<circle class="hd" data-h="d" cx="' + w + '" cy="' + w / 2 + '" r="' + hs + '"/>';
  } else if (o.shape === "slot") {
    shape = '<rect class="ol" x="0" y="0" width="' + w + '" height="' + hh + '" rx="' + hh / 2 + '"/>';
    handles = '<circle class="hd" data-h="len" cx="' + w + '" cy="' + hh / 2 + '" r="' + hs + '"/><circle class="hd" data-h="wid" cx="' + w / 2 + '" cy="' + hh + '" r="' + hs + '"/>';
  } else {
    shape = '<polygon class="ol" points="' + o.points.map(p => p.join(",")).join(" ") + '"/>';
    handles = o.points.map((p, i) => '<circle class="hd' + (o.sel === i ? " sel" : "") + '" data-h="pt" data-i="' + i + '" cx="' + p[0] + '" cy="' + p[1] + '" r="' + hs + '"/>').join("");
  }
  const holes = o.holes.map(x => {
    const r = (x.kind === "circle" ? num(x.dia) || 3 : Math.max(num(x.hlen) || 8, num(x.hwid) || 2)) / 2;
    let cx = w / 2, cy = hh / 2;
    if (x.at === "edge") { const web = num(o.web) || 1; if (x.edge === "NORTH") cy = web + r; else if (x.edge === "SOUTH") cy = hh - web - r; else if (x.edge === "WEST") cx = web + r; else cx = w - web - r; }
    else { const rad = num(x.rad) || 0; const ang = {EAST: 0, SOUTH: 90, WEST: 180, NORTH: 270}[x.bearing] * Math.PI / 180; cx += rad * Math.cos(ang); cy += rad * Math.sin(ang); }
    return '<circle class="hole" cx="' + cx + '" cy="' + cy + '" r="' + r + '"/>';
  }).join("");
  const grid = []; const step = w > 80 ? 10 : 5;
  for (let x = 0; x <= w; x += step) grid.push('<line class="grd" x1="' + x + '" y1="0" x2="' + x + '" y2="' + hh + '"/>');
  for (let y = 0; y <= hh; y += step) grid.push('<line class="grd" x1="0" y1="' + y + '" x2="' + w + '" y2="' + y + '"/>');
  svg.innerHTML = shape + grid.join("") + holes + handles + '<text x="0" y="-2">' + (isRect(o.shape) ? h(mmTxt(w) + " x " + mmTxt(hh) + " mm") : "") + "</text>";
  qa("[data-h]", svg).forEach(c => c.onpointerdown = e => olDrag(e, c, svg));
  if (o.shape === "polygon") svg.onclick = e => { if (e.target.dataset && e.target.dataset.h) return; };
}
const mmTxt = v => String(Math.round(v * 100) / 100);
function olDrag(e, c, svg) {
  e.preventDefault(); c.setPointerCapture(e.pointerId);
  const o = BS.ol, grid = (BS.st.settings && BS.st.settings.grid_mm) || 0.5;
  const snap = v => Math.round(v / grid) * grid;
  const at = ev => { const pt = svg.createSVGPoint(); pt.x = ev.clientX; pt.y = ev.clientY; const p = pt.matrixTransform(svg.getScreenCTM().inverse()); return [p.x, p.y]; };
  const move = ev => {
    const [x, y] = at(ev), k = c.dataset.h;
    o.typed = true;
    if (k === "w") o.w = String(Math.max(grid, snap(x))); else if (k === "h") o.h = String(Math.max(grid, snap(y)));
    else if (k === "d") o.d = String(Math.max(grid, snap(x))); else if (k === "len") o.len = String(Math.max(grid, snap(x))); else if (k === "wid") o.wid = String(Math.max(grid, snap(y)));
    else if (k === "pt") { o.points[+c.dataset.i] = [Math.max(0, snap(x)), Math.max(0, snap(y))]; o.sel = +c.dataset.i; }
    drawOutlineValues();
  };
  const up = () => { c.removeEventListener("pointermove", move); c.removeEventListener("pointerup", up); askSuggestion(); };
  c.addEventListener("pointermove", move); c.addEventListener("pointerup", up);
}
async function olGo(mode) {
  const o = BS.ol, err = q("#ol-err");
  err.textContent = "";
  const spec = olSpec(o);
  try {
    if (mode === "create") {
      await post("/build/outline/create", {spec, description: o.desc});
      BS.ol = null; BS.closed = false; say("The layout script is written.", "good");
      return;
    }
    const rid = BS.parts && BS.parts.resolve;
    const r = await post("/build/offer", {kind: "outline", resolve: rid, spec, params: {choices: o.choices}});
    await applyOffer(r.offers[0]);
    document.body.classList.remove("bld-ol"); closeOutlineDialog();
  } catch (e) {
    err.textContent = e.message;
    if (e.data && e.data.affected) {
      o.affected = e.data.affected;
      q("#ol-aff").innerHTML = '<div class="bld-msg bad">These placements stop being valid. Choose for each:</div>' + e.data.affected.map(a => '<div class="bld-row"><b>' + h(a.label) + '</b> <span class="bld-note">' + h(a.phrase) + '</span><select data-aff="' + h(a.key) + '">' + a.choices.map(c => "<option>" + h(c === "rim" ? "rim" : c === "edge" ? "edge" : c) + "</option>").join("") + "</select></div>").join("");
      qa("[data-aff]").forEach(s => { o.choices[s.dataset.aff] = s.value; s.onchange = () => { o.choices[s.dataset.aff] = s.value; }; });
    }
  }
}
// the outline of a script that exists: a dialog over the page
let olDlg = null;
function openOutlineDialog() {
  if (!BS.parts || !BS.parts.outline) return say("The script has no outline the builder can read.", "bad");
  BS.ol = newOutline(BS.parts); BS.ol.mode = "change";
  olDlg = document.createElement("div"); olDlg.id = "bld-oldlg"; olDlg.style.cssText = "position:fixed;inset:0;z-index:70;background:var(--bg);display:flex;flex-direction:column";
  olDlg.innerHTML = '<div class="bh" style="display:flex;gap:10px;padding:8px 14px;background:var(--surface);border-bottom:1px solid var(--line)"><b>Outline</b><span style="flex:1"></span><button class="bld-btn" id="oldlg-close">Close</button></div><div class="bb" style="flex:1;overflow:auto;padding:16px"><div class="bld-wrap"><div id="bld-msg"></div><div id="ol-body"></div></div></div>';
  document.body.appendChild(olDlg);
  q("#oldlg-close").onclick = closeOutlineDialog;
  drawOutline(q("#ol-body"), "change");
  if (!BS.ol.readOnly) askSuggestion && void 0;
}
function closeOutlineDialog() { if (olDlg) { olDlg.remove(); olDlg = null; } BS.ol = null; }

// ---------------------------------------------------------------- the Build tab: the parts list and the relation menu
function counts() { return BS.parts ? BS.parts.counts : {unplaced: 0, searched: 0, decided: 0, "by hand": 0}; }
function drawTab() {
  const el = tabPane;
  if (!hasScript()) { el.innerHTML = ""; return; }
  const mine = BS.st && BS.st.session && BS.st.session.script && BS.st.session.script.endsWith(S.hello.script);
  if (!BS.st || !mine || BS.st.phase !== "ready") {
    const working = BS.st && mine && (BS.st.phase === "working");
    const bad = BS.st && mine && BS.st.phase === "error";
    el.innerHTML = '<div class="bt-sec"><div id="bt-msg"></div>' + (working ? '<div class="row"><i class="spin"></i> ' + h(BS.st.text || "reading the board") + "</div>" :
      bad ? '<div class="bld-msg bad">' + h(BS.st.text) + '</div><button class="bld-btn" id="bt-open">Try again</button>' :
      '<p class="bld-note">The builder reads this script\'s board, states its facts, and writes placements as relations. It opens on the board the script lays out.</p><button class="bld-btn primary" id="bt-open">Open the builder</button>') + "</div>";
    const ob = q("#bt-open"); if (ob) ob.onclick = openSession;
    return;
  }
  const p = BS.parts, c = counts();
  q('[data-count="build"]', tabBtn).textContent = p ? String(c.unplaced) : "";
  const gate = BS.facts && BS.facts.model.gate;
  const rows = p ? filtered(p.rows) : [];
  const sel = new Set(BS.subj);
  const nets = shared(p, sel);
  el.innerHTML = '<div class="bt-head"><div id="bt-msg"></div><div class="bld-row tight"><b>' + c.unplaced + ' unplaced, ' + c.searched + ' searched, ' + c.decided + ' decided' + (c["by hand"] ? ", " + c["by hand"] + " by hand" : "") + '</b><span style="flex:1"></span>' +
    '<button class="bld-btn" id="bt-undo"' + (S.applied.some(a => !a.undone) ? "" : " disabled") + ' title="undo the last builder action">Undo</button><button class="bld-btn" id="bt-redo"' + (S.redo ? "" : " disabled") + ">Redo</button></div>" +
    (gate && !gate.open ? '<div class="bld-gate">Placement waits for the facts: ' + h((BS.facts.model.reasons.map(r => r.text).join("; ")) || "confirm them") + ' <button class="bld-btn" id="bt-facts">Facts</button></div>' : "") +
    '<div class="bld-row tight"><button class="bld-btn" id="bt-outline">Outline</button><button class="bld-btn" id="bt-factsb">Facts</button><button class="bld-btn primary" id="bt-search"' + (gate && gate.open && c.unplaced ? "" : " disabled") + ' title="one plain place() for each item left, in the searched block">Search the rest</button>' +
    '<label class="bld-note"><input type="checkbox" id="bt-either"> either face</label></div></div>' +
    '<div class="bt-sec" id="bt-sel"></div>' +
    '<div class="bt-sec"><div class="bld-row tight"><select id="bt-fs" class="bld-in" style="max-width:130px"><option value="">all</option>' + ["unplaced", "searched", "decided", "by hand"].map(s => '<option' + (BS.filter.status === s ? " selected" : "") + ">" + s + "</option>").join("") + '</select><input id="bt-ft" class="bld-in" placeholder="filter by name or value" value="' + h(BS.filter.text) + '"></div></div>' +
    '<div id="bt-list">' + (p ? rows.map(r => rowHtml(r, sel, nets)).join("") : '<div class="bt-sec bld-note">Reading ...</div>') + '</div>' +
    '<div class="bt-sec"><h3>Tray: unplaced items, drawn to size</h3><div class="bt-tray" id="bt-tray">' + (p ? p.rows.filter(r => r.status === "unplaced").map(r => '<div data-key="' + h(r.key) + '" class="' + (sel.has(r.key) ? "sel" : "") + '" style="width:' + Math.max(18, r.w * 3) + "px;height:" + Math.max(12, r.h * 3) + 'px" title="' + h(r.ref + " " + r.w + " x " + r.h + " mm") + '">' + h(r.ref.length < 8 ? r.ref : "") + "</div>").join("") : "") + '</div></div>' +
    '<div class="bt-sec"><h3>Timeline</h3><div id="bt-tl"></div><div id="bt-tld"></div></div>';
  drawMsg(); drawSelection(); drawTimeline(); foldUnplaced();
  q("#bt-undo").onclick = undo; q("#bt-redo").onclick = redo;
  const fb = q("#bt-facts"); if (fb) fb.onclick = openFacts;
  q("#bt-factsb").onclick = openFacts;
  q("#bt-outline").onclick = openOutlineDialog;
  q("#bt-search").onclick = searchRest;
  q("#bt-fs").onchange = e => { BS.filter.status = e.target.value; drawTab(); };
  q("#bt-ft").oninput = e => { BS.filter.text = e.target.value; clearTimeout(drawTab.t); drawTab.t = setTimeout(() => { drawTab(); const i = q("#bt-ft"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }, 200); };
  q("#bt-list").onclick = e => { const r = e.target.closest("[data-key]"); if (r) clickRow(r.dataset.key, e); };
  q("#bt-tray").onclick = e => { const r = e.target.closest("[data-key]"); if (r) clickRow(r.dataset.key, e); };
}
function openFacts() { BS.closed = false; BS.step = "facts"; S.hello = S.hello; factsOverlay(); }
function factsOverlay() {
  // the facts of a script that exists: the same flow, in the overlay, over the page
  const sess = BS.st && BS.st.session;
  wiz.hidden = false; BS.overlayFacts = true;
  const steps = '<div class="steps"><button class="on">Facts</button></div>';
  wiz.innerHTML = '<div class="bh"><b>Facts: ' + h(sess.name) + "</b>" + steps + '<span style="flex:1"></span><button class="bld-btn" id="bld-undo"' + (S.applied.some(a => !a.undone) ? "" : " disabled") + '>Undo</button><button class="bld-btn" id="bld-close">Close</button></div><div class="bb"><div class="bld-wrap"><div id="bld-msg"></div><div id="bld-body"></div></div></div>';
  q("#bld-close").onclick = () => { wiz.hidden = true; BS.overlayFacts = false; refreshParts(); };
  q("#bld-undo").onclick = undo;
  const body = q("#bld-body");
  factsStep(body);
}
function filtered(rows) {
  const f = BS.filter, t = f.text.trim().toLowerCase();
  return rows.filter(r => (!f.status || r.status === f.status) && (!t || (r.ref + " " + r.value + " " + r.key + " " + (r.cell || "")).toLowerCase().includes(t)));
}
function shared(p, sel) {
  const out = {}; if (!p || !sel.size) return out;
  const mine = new Set(); for (const r of p.rows) if (sel.has(r.key)) r.nets.forEach(n => mine.add(n));
  for (const r of p.rows) if (!sel.has(r.key)) { const n = r.nets.filter(x => mine.has(x)).length; if (n) out[r.key] = n; }
  return out;
}
function rowHtml(r, sel, nets) {
  const chip = '<span class="chip ' + (r.status === "unplaced" ? "unplaced" : r.status === "decided" ? "decided" : r.status === "searched" ? "searched" : "warn") + '">' + h(r.status) + "</span>";
  const tg = BS.target && BS.target.key === r.key;
  return '<div class="bt-prow' + (sel.has(r.key) ? " sel" : "") + (tg ? " tgt" : "") + '" data-key="' + h(r.key) + '"><input type="checkbox" tabindex="-1"' + (sel.has(r.key) ? " checked" : "") + '><div><b>' + h(r.ref) + '</b> <span class="sub">' + h(r.value) + '</span><div class="sub">' + (r.cell ? h(r.cell) + " · " : "") + h(r.w + " x " + r.h + " mm · " + r.pads + " pads") + (r.kind === "cell" ? " · cell" : "") + '</div></div><div class="sub">' + h(r.phrase || r.mark || "") + (r.source ? "<br><code>" + h(r.source) + "</code>" : "") + '</div><div>' + chip + (nets[r.key] ? '<div class="sh">' + nets[r.key] + " shared net" + (nets[r.key] > 1 ? "s" : "") + "</div>" : "") + "</div></div>";
}
function clickRow(key, ev) {
  const row = BS.parts && BS.parts.rows.find(r => r.key === key);
  if (!row) return;
  if (BS.subj.length && BS.chip !== "edge" && BS.chip !== "none" && !BS.subj.includes(key) && BS.target !== undefined && (BS.chip === "part" || BS.chip === "pad")) { setTarget({kind: BS.chip, key}); return; }
  const i = BS.subj.indexOf(key);
  if (i >= 0) BS.subj.splice(i, 1);
  else if (ev && (ev.shiftKey || ev.ctrlKey || ev.metaKey || ev.target.type === "checkbox")) BS.subj.push(key);
  else BS.subj = [key];
  BS.target = null; BS.offers = null; BS.diff = null; BS.tried = null; BS.turns = null;
  if (BS.subj.length === 1 && S.itemAt && S.itemAt.has(key)) { try { selectItem(key, {zoom: true}); } catch (e) { /* the board draws what it has */ } }
  document.body.classList.toggle("bld-picking", BS.subj.length > 0);
  drawTab();
}
// the panel for what is selected: how it is placed, what a click picks, the menu
function drawSelection() {
  const el = q("#bt-sel"); if (!el) return;
  const rows = (BS.parts ? BS.parts.rows : []).filter(r => BS.subj.includes(r.key));
  if (!rows.length) { el.innerHTML = '<span class="bld-note">Select an unplaced part or cell, in the list, the tray or on the board. Then say what it goes by: an edge, a part, a pad, or the search.</span>'; return; }
  const one = rows.length === 1 ? rows[0] : null;
  const rect = BS.parts.outline && BS.parts.outline.kind === "rect", disc = BS.parts.outline && BS.parts.outline.kind === "disc";
  const pick = (BS.chip === "part" || BS.chip === "pad");
  el.innerHTML = '<h3>' + h(rows.map(r => r.ref).join(", ")) + (one && one.phrase ? ' <span class="bld-note">now ' + h(one.phrase) + "</span>" : "") + '</h3>' +
    (rows.length > 1 ? '<div class="bld-note">Several selected: they go in a row along an edge or beside a part (a ring round a disc\'s rim), in this order:</div><div class="bt-chips" id="bt-order">' + orderKeys(rows).map((k, i) => '<button data-up="' + i + '" title="earlier">' + h((BS.parts.rows.find(r => r.key === k) || {}).ref || k) + " \u25c0</button>").join("") + "</div>" : "") +
    '<div class="bld-note">A click picks:</div><div class="bt-chips" id="bt-chips">' + [["edge", "Edge"], ["part", "Part"], ["pad", "Pad"], ["none", "None (search)"]].map(c => '<button data-chip="' + c[0] + '" class="' + (BS.chip === c[0] ? "on" : "") + '">' + c[1] + "</button>").join("") + "</div>" +
    '<div id="bt-tg" style="margin-top:6px"></div><div id="bt-menu"></div><div id="bt-turns"></div><div id="bt-edit"></div>';
  qa("[data-up]", el).forEach(b => b.onclick = () => { const i = +b.dataset.up; if (i > 0) { const o = BS.order; [o[i - 1], o[i]] = [o[i], o[i - 1]]; BS.offers = null; drawSelection(); if (BS.target) askOffers(); } });
  qa("[data-chip]", el).forEach(b => b.onclick = () => { BS.chip = b.dataset.chip; BS.target = BS.chip === "none" ? {kind: "none"} : null; BS.offers = null; if (BS.chip === "none") askOffers(); drawSelection(); });
  drawTarget(rect, disc); drawMenu(); drawEdit(one);
  if (BS.turns) drawTurns();
}
function orderKeys(rows) { const keys = rows.map(r => r.key); const cur = BS.order && BS.order.length === keys.length && keys.every(k => BS.order.includes(k)) ? BS.order : keys; BS.order = cur; return cur; }
function drawTarget(rect, disc) {
  const el = q("#bt-tg"); if (!el) return;
  const t = BS.target;
  if (BS.chip === "edge") {
    const o = BS.parts.outline;
    if (!o || !(o.kind === "rect" || o.kind === "disc" || o.kind === "outline")) { el.innerHTML = '<div class="bld-note">This outline is not one the builder places on (a fit frame is derived from its content).</div>'; return; }
    el.innerHTML = '<div class="bt-side">' + (o.kind !== "disc" ? (o.kind === "outline" ? '<span class="bld-note">the stretch of edge facing:</span> ' : "") + SIDES.map(s => '<button data-edge="' + s + '" class="' + (t && t.edge === s ? "on" : "") + '">' + SIDE_WORD[s] + "</button>").join(" ") :
      SIDES.map(s => '<button data-edge="' + s + '" class="' + (t && t.edge === s && !t.bore ? "on" : "") + '">rim ' + SIDE_WORD[s] + '</button>').join(" ") + ' <button data-rim="1" class="' + (t && t.rim ? "on" : "") + '">anywhere on the rim</button>') + '</div><div class="bld-note">or click the board near the edge.</div>';
    qa("[data-edge]", el).forEach(b => b.onclick = () => setTarget({kind: "edge", edge: b.dataset.edge}));
    const rim = q("[data-rim]", el); if (rim) rim.onclick = () => setTarget({kind: "edge", rim: true});
  } else if (BS.chip === "part" || BS.chip === "pad") {
    if (!t || !t.key) { el.innerHTML = '<div class="bld-note">Click a placed or searched part ' + (BS.chip === "pad" ? "(then its pad) " : "") + "on the board or in the list. An unplaced part is not a target: it has no place to be beside.</div>"; return; }
    const r = BS.parts.rows.find(x => x.key === t.key);
    const sideBtns = '<div class="bt-side">' + SIDES.map(s => '<button data-side="' + s + '" class="' + (t.side === s ? "on" : "") + '">' + SIDE_WORD[s] + "</button>").join(" ") + "</div>";
    if (BS.chip === "pad") {
      const pads = (r && r.pad_list) || [];
      el.innerHTML = "<div>Pad of <b>" + h(r ? r.ref : t.key) + '</b></div><select id="bt-pad" class="bld-in"><option value="">choose a pad</option>' + pads.map(p => '<option value="' + h(p.number) + '"' + (t.pad === p.number ? " selected" : "") + ">" + h(p.number + (p.net ? " (" + p.net + ")" : "")) + "</option>").join("") + "</select>" + (pads.length ? "" : '<div class="bld-note">A cell has no pad of its own: choose a part.</div>');
      const s = q("#bt-pad", el); if (s) s.onchange = () => { t.pad = s.value; if (t.pad) askOffers(); };
    } else el.innerHTML = "<div>Beside <b>" + h(r ? r.ref : t.key) + "</b>: which side?</div>" + sideBtns;
    qa("[data-side]", el).forEach(b => b.onclick = () => { t.side = b.dataset.side; askOffers(); drawTarget(); });
  } else el.innerHTML = '<div class="bld-note">Leave it to the search: a plain place(), seeded from its links.</div>';
}
function setTarget(t) { BS.target = t; BS.offers = null; BS.diff = null; BS.tried = null; if (t.kind === "edge" || t.kind === "none" || (t.kind === "part" && t.side)) askOffers(); drawSelection(); }
let offerTimer = null;
function paramsNow() {
  const p = {}, g = q("#bt-gap"); if (g && g.value) { p.gap = num(g.value); p.gap_note = (q("#bt-gapnote") || {}).value || ""; }
  if (BS.subj.length > 1) p.order = BS.order;
  const fp = (q("#bt-p-fpad") || {}).value, fe = (q("#bt-p-fedge") || {}).value, tp = (q("#bt-p-tpart") || {}).value;
  if (fp && fe) p.facing = {pad: fp, edge: fe};
  if (tp) p.turned = {key: tp, degrees: parseInt((q("#bt-p-tdeg") || {}).value || "0", 10)};
  for (const k of ["rotation", "face", "priority", "why", "side", "own_pad", "radius", "limit_mm"]) { const i = q("#bt-p-" + k); if (i && i.value !== "") p[k] = k === "rotation" ? parseInt(i.value, 10) : (["radius", "limit_mm"].includes(k) ? num(i.value) : i.value); }
  const rq = q("#bt-p-required"); if (rq && rq.checked) p.required = true;
  return p;
}
function askOffers(keepParams) {
  clearTimeout(offerTimer);
  offerTimer = setTimeout(async () => {
    if (!BS.subj.length) return;
    const t = BS.target; if (!t) return;
    const target = t.kind === "none" ? null : t.kind === "edge" ? (t.rim ? {kind: "edge", rim: true} : {kind: "edge", edge: t.edge}) : t.kind === "part" ? {kind: "part", key: t.key, side: t.side} : {kind: "pad", key: t.key, pad: t.pad};
    try {
      const r = await post("/build/offer", {resolve: BS.parts.resolve, subject: BS.subj, target, params: keepParams === false ? {} : paramsNow()});
      BS.offers = r.offers; BS.menuError = null;
    } catch (e) { BS.offers = null; BS.menuError = e.message; }
    BS.diff = null; BS.tried = null; drawMenu();
  }, 100);
}
function drawMenu() {
  const el = q("#bt-menu"); if (!el) return;
  if (BS.menuError) { el.innerHTML = '<div class="bld-msg bad">' + h(BS.menuError) + "</div>"; return; }
  if (!BS.offers) { el.innerHTML = ""; return; }
  const P = BS.params;
  el.innerHTML = '<div class="bld-note" style="margin-top:6px">Choose the relation:</div>' + BS.offers.map(o => '<div class="bt-offer' + (o.needs && o.needs.length ? " need" : "") + '"><div class="bld-row"><b>' + h(o.text) + '</b><span style="flex:1"></span>' + (o.id ? '<button class="bld-btn" data-show="' + o.id + '">Show</button><button class="bld-btn" data-try="' + o.id + '">Try</button><button class="bld-btn primary" data-place="' + o.id + '"' + (BS.applying ? " disabled" : "") + ">Place</button>" : "") + "</div>" +
    (o.needs && o.needs.length ? '<div class="bld-note">Needs: ' + h(o.needs.join(", ")) + " (below)</div>" : "") +
    (o.preview ? Object.values(o.preview).map(v => '<div class="bld-pre">' + v.removed.map(l => '<div class="del">- ' + h(l) + "</div>").join("") + v.added.map(l => '<div class="add">+ ' + h(l) + "</div>").join("") + "</div>").join("") : "") + (o.refused ? '<div class="bld-msg bad">' + h(o.refused) + "</div>" : "") + "</div>").join("") +
    '<details class="bld-card" ' + (BS.paramsOpen ? "open" : "") + ' id="bt-params"><summary>Gap, turn, face, priority, note</summary><div class="bld-grid" style="margin-top:6px">' +
    '<label class="bld-f">Gap, mm<input id="bt-gap" inputmode="decimal" value="' + h(BS.pv.gap || "") + '"></label><label class="bld-f">Why the gap (required)<input id="bt-gapnote" value="' + h(BS.pv.gapnote || "") + '"></label>' +
    '<label class="bld-f">Own pad (to link or level)<input id="bt-p-own_pad" value="' + h(BS.pv.own_pad || "") + '" placeholder="pad number"></label><label class="bld-f">Side (level with a pad)<select id="bt-p-side"><option value=""></option>' + SIDES.map(s => "<option" + (BS.pv.side === s ? " selected" : "") + ">" + s + "</option>").join("") + "</select></label>" +
    '<label class="bld-f">Quarter turn<select id="bt-p-rotation"><option value=""></option>' + [0, 90, 180, 270].map(d => "<option" + (String(BS.pv.rotation) === String(d) ? " selected" : "") + ">" + d + "</option>").join("") + "</select></label>" +
    '<label class="bld-f">Pad facing an edge: pad<input id="bt-p-fpad" value="' + h(BS.pv.fpad || "") + '" placeholder="own pad"></label><label class="bld-f">...faces<select id="bt-p-fedge"><option value=""></option>' + SIDES.map(s => "<option" + (BS.pv.fedge === s ? " selected" : "") + ">" + s + "</option>").join("") + "</select></label>" +
    '<label class="bld-f">Turned with<select id="bt-p-tpart"><option value=""></option>' + (BS.parts ? BS.parts.rows.filter(r => r.status !== "unplaced" && !BS.subj.includes(r.key)).map(r => '<option value="' + h(r.key) + '"' + (BS.pv.tpart === r.key ? " selected" : "") + ">" + h(r.ref) + "</option>").join("") : "") + '</select></label><label class="bld-f">...plus<select id="bt-p-tdeg">' + [0, 90, 180, 270].map(d => "<option" + (String(BS.pv.tdeg) === String(d) ? " selected" : "") + ">" + d + "</option>").join("") + "</select></label>" +
    '<label class="bld-f">Face<select id="bt-p-face"><option value="">front</option><option' + (BS.pv.face === "BACK" ? " selected" : "") + '>BACK</option><option' + (BS.pv.face === "EITHER" ? " selected" : "") + ">EITHER</option></select></label>" +
    '<label class="bld-f">Priority (needs a why)<select id="bt-p-priority"><option value=""></option><option' + (BS.pv.priority === "HIGH" ? " selected" : "") + '>HIGH</option><option' + (BS.pv.priority === "LOW" ? " selected" : "") + ">LOW</option></select></label>" +
    '<label class="bld-f">Note (why=)<input id="bt-p-why" value="' + h(BS.pv.why || "") + '"></label><label class="bld-f">Link limit, mm<input id="bt-p-limit_mm" value="' + h(BS.pv.limit || "") + '"></label><label class="bld-f">Near radius, mm<input id="bt-p-radius" value="' + h(BS.pv.radius || "") + '"></label>' +
    '<label class="bld-row"><input type="checkbox" id="bt-p-required"' + (BS.pv.required ? " checked" : "") + '> required</label></div></details><div id="bt-diff"></div>';
  qa("#bt-params input, #bt-params select", el).forEach(i => i.onchange = i.oninput = () => { BS.pv = readPv(); BS.paramsOpen = true; askOffers(); });
  qa("[data-show]", el).forEach(b => b.onclick = () => showOffer(b.dataset.show));
  qa("[data-try]", el).forEach(b => b.onclick = () => tryOffer(b.dataset.try));
  qa("[data-place]", el).forEach(b => b.onclick = () => placeOffer(b.dataset.place));
  drawDiff();
}
BS.pv = {};
function readPv() {
  const g = id => (q("#bt-" + id) || {}).value || "";
  return {gap: g("gap"), gapnote: g("gapnote"), own_pad: g("p-own_pad"), side: g("p-side"), rotation: g("p-rotation"), face: g("p-face"), priority: g("p-priority"), why: g("p-why"), fpad: g("p-fpad"), fedge: g("p-fedge"), tpart: g("p-tpart"), tdeg: g("p-tdeg"), limit: g("p-limit_mm"), radius: g("p-radius"), required: !!(q("#bt-p-required") || {}).checked};
}
function drawDiff() {
  const el = q("#bt-diff"); if (!el) return;
  el.innerHTML = (BS.diff ? '<div class="bld-pre">' + BS.diff.diff.split("\n").map(l => '<div class="' + (l.startsWith("+") && !l.startsWith("+++") ? "add" : l.startsWith("-") && !l.startsWith("---") ? "del" : "") + '">' + h(l) + "</div>").join("") + "</div>" : "") +
    (BS.tried ? '<div class="bld-msg ' + (BS.tried.state === "done" ? "info" : "bad") + '">' + (BS.tried.state === "done" ? "Try (nothing written): " + h(BS.tried.gained.length + " findings gained, " + BS.tried.lost.length + " lost, " + BS.tried.moved + " items moved") : h(BS.tried.message || BS.tried.state)) + "</div>" : "");
}
async function showOffer(id) { try { BS.diff = await post("/suggest/show", {resolve: BS.parts.resolve, id}); } catch (e) { say(e.message, "bad"); } drawDiff(); }
async function tryOffer(id) {
  say("Trying: resolving the edited script, nothing written ...", "info");
  try { BS.tried = await post("/suggest/try", {resolve: BS.parts.resolve, id}); say("", ""); } catch (e) { BS.tried = {state: "error", message: e.message}; say("", ""); }
  drawDiff();
}
async function applyOffer(o) { return post("/suggest/apply", {resolve: BS.parts.resolve, id: o.id}); }
async function placeOffer(id) {
  if (BS.applying) return; BS.applying = true;
  const subj = BS.subj.slice(), tgt = BS.target;
  try {
    await applyOffer({id}); say("Placed. The board resolves again.", "good");
    BS.offers = null; BS.target = null; BS.diff = null; BS.tried = null; BS.pendingTurn = subj.length === 1 && tgt && tgt.kind !== "none" ? subj[0] : null; BS.subj = subj; BS.chip = "edge";
  } catch (e) { say(e.message, "bad"); }
  BS.applying = false; drawTab();
}
async function searchRest() {
  const either = !!(q("#bt-either") || {}).checked;
  const keys = BS.subj.length ? BS.subj.filter(k => (BS.parts.rows.find(r => r.key === k) || {}).status === "unplaced") : undefined;
  try {
    const r = await post("/build/offer", {kind: "search", resolve: BS.parts.resolve, either_face: either, keys: keys && keys.length ? keys : undefined});
    if (!confirm("Search the rest: write " + r.offers[0].count + " plain place() statement(s) in one block?")) return;
    await applyOffer(r.offers[0]); say("Searching the rest. The board resolves again.", "good"); BS.subj = [];
  } catch (e) { say(e.message, "bad"); }
  drawTab();
}
// a placed item: take it off, leave it to the search, change a modifier
function drawEdit(one) {
  const el = q("#bt-edit"); if (!el) return;
  if (!one || one.status === "unplaced") { el.innerHTML = ""; return; }
  el.innerHTML = '<div class="bld-row" style="margin-top:8px"><button class="bld-btn" id="bt-remove">Take it off the board</button>' + (one.status === "decided" ? '<button class="bld-btn" id="bt-tosearch">Leave it to the search</button>' : "") + '<button class="bld-btn" id="bt-turnbtn">Suggest a turn</button></div>' +
    (one.status === "by hand" ? '<div class="bld-note">A declaration the builder cannot read as one of its intents: shown as written; it offers only "replace by a relation" (pick a target above).</div>' : "") +
    '<div class="bld-note">Modifiers now: ' + h(JSON.stringify(one.mods || {})) + "</div>";
  const mv = async (dir) => { try { const r = await post("/build/offer", {kind: "move", resolve: BS.parts.resolve, subject: [one.key], params: {direction: dir}}); await applyOffer(r.offers[0]); say("Moved " + dir + ".", "info"); } catch (e) { say(e.message, "bad"); } drawTab(); };
  if (one.status === "decided" && (!one.relation || one.relation.kind !== "row")) el.insertAdjacentHTML("beforeend", '<div class="bld-row tight" style="margin-top:6px"><span class="bld-note">Order among the decided placements:</span><button class="bld-btn" id="bt-up">Up</button><button class="bld-btn" id="bt-down">Down</button></div>');
  if (one.relation && one.relation.kind === "row") el.insertAdjacentHTML("beforeend", '<div class="bld-row tight" style="margin-top:6px"><button class="bld-btn" id="bt-outrow">Take it out of its row</button></div>');
  const bu = q("#bt-up", el), bd = q("#bt-down", el), orow = q("#bt-outrow", el);
  if (bu) { bu.onclick = () => mv("up"); bd.onclick = () => mv("down"); }
  if (orow) orow.onclick = async () => { try { const r = await post("/build/offer", {kind: "row", resolve: BS.parts.resolve, subject: [one.key], params: {action: "remove", member: one.key}}); await applyOffer(r.offers[0]); say("Taken out of its row.", "info"); BS.subj = []; } catch (e) { say(e.message, "bad"); } drawTab(); };
  q("#bt-remove").onclick = async () => { try { const r = await post("/build/offer", {kind: "remove", resolve: BS.parts.resolve, subject: [one.key]}); await applyOffer(r.offers[0]); say("Taken off.", "info"); BS.subj = []; } catch (e) { say(e.message, "bad"); } drawTab(); };
  const ts = q("#bt-tosearch"); if (ts) ts.onclick = () => { BS.chip = "none"; setTarget({kind: "none"}); };
  q("#bt-turnbtn").onclick = () => loadTurns(one.key);
}
async function loadTurns(key) {
  try { BS.turns = await post("/build/turns", {resolve: BS.parts.resolve, subject: key}); } catch (e) { BS.turns = null; say(e.message, "bad"); }
  drawTurns();
}
function drawTurns() {
  const el = q("#bt-turns"); if (!el) return;
  const t = BS.turns; if (!t) { el.innerHTML = ""; return; }
  el.innerHTML = '<div class="bld-note" style="margin-top:8px">Ratsnest crossings of each quarter turn (an estimate; Try resolves it exactly). Marked: the fewest' + (t.tie ? " (a tie)" : "") + '.</div><div class="bt-turn">' + t.turns.map(x => '<button data-turn="' + x.rotation + '" class="' + (x.rotation === t.best ? "best" : "") + '">' + x.rotation + "°: " + x.crossings + " crossing" + (x.crossings === 1 ? "" : "s") + (x.rotation === t.current ? " (now)" : "") + "</button>").join("") + "</div>";
  qa("[data-turn]", el).forEach(b => b.onclick = async () => {
    try { const r = await post("/build/turn", {resolve: BS.parts.resolve, subject: t.subject, rotation: +b.dataset.turn}); BS.offers = r.offers; BS.turns = null; drawSelection(); drawMenu(); say("Check the statement, then Place.", "info"); } catch (e) { say(e.message, "bad"); }
  });
}
// the timeline: the studio's resolve history, each builder action a row labelled by its phrase
function drawTimeline() {
  const el = q("#bt-tl"); if (!el) return;
  const hist = (S.history || []).slice().reverse();
  el.innerHTML = hist.length ? hist.slice(0, 40).map((x, i) => '<div class="bt-tl" data-r="' + x.id + '"><b>#' + x.id + "</b><span>" + h((x.applied || (x.changed && x.changed.length ? "edited: " + x.changed.join(", ") : "resolved")).replace(/^applied from a suggestion: /, "")) + '</span><span class="bld-note">' + h(x.counts ? x.counts.findings + " findings" : "") + "</span></div>").join("") : '<div class="bld-note">No resolves yet.</div>';
  el.onclick = async e => {
    const r = e.target.closest("[data-r]"); if (!r) return;
    const id = +r.dataset.r, prev = (S.history || []).filter(x => x.id < id).pop();
    const d = q("#bt-tld"); if (!prev) { d.innerHTML = '<div class="bld-note">The first resolve has nothing before it.</div>'; return; }
    try { const c = await get("/diff?a=" + prev.id + "&b=" + id); const f = c.diff.findings; d.innerHTML = '<div class="bld-note">#' + id + " against #" + prev.id + ": " + f.gained.length + " findings gained, " + f.lost.length + " lost, " + c.diff.moved.length + " items moved. <a href=\"#\" id=\"bt-cmp\">Open in Compare</a></div>"; q("#bt-cmp").onclick = ev => { ev.preventDefault(); try { S.baseId = prev.id; S.shownId = id; } catch (x) { /* the Compare tab picks its own */ } goTab("compare"); }; }
    catch (x) { d.innerHTML = '<div class="bld-note">' + h(x.message) + "</div>"; }
  };
}

// ---------------------------------------------------------------- clicks on the board pick a target (never a position)
$("#board").addEventListener("click", ev => {
  if (!BS.subj.length || !BS.parts || !hasScript() || S.cmdView) return;
  const grp = ev.target.closest && ev.target.closest(".item");
  const key = grp && grp.dataset.key;
  const svg = $("#board");
  if (BS.chip === "edge") {
    const o = BS.parts.outline; if (!o || !(o.kind === "rect" || o.kind === "disc" || o.kind === "outline")) return;
    const r = svg.getBoundingClientRect(), vb = S.vb; if (!vb) return;
    const x = vb.x + (ev.clientX - r.left) / r.width * vb.w, y = vb.y + (ev.clientY - r.top) / r.height * vb.h, e = (plan() && plan().board && plan().board.extent) || [0, 0, 60, 40];
    const d = {WEST: x - e[0], EAST: e[2] - x, NORTH: y - e[1], SOUTH: e[3] - y}, near = Object.keys(d).reduce((a, b) => Math.abs(d[a]) < Math.abs(d[b]) ? a : b);
    if (o.kind === "disc") setTarget({kind: "edge", edge: near}); else setTarget({kind: "edge", edge: near});
    ev.stopPropagation(); return;
  }
  if ((BS.chip === "part" || BS.chip === "pad") && key && !BS.subj.includes(key)) {
    const row = BS.parts.rows.find(r => r.key === key); if (!row || row.status === "unplaced") return;
    const rc = grp.getBoundingClientRect(), dx = (ev.clientX - (rc.left + rc.right) / 2) / Math.max(1, rc.width), dy = (ev.clientY - (rc.top + rc.bottom) / 2) / Math.max(1, rc.height);
    const side = Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? "EAST" : "WEST") : (dy > 0 ? "SOUTH" : "NORTH");
    const t = {kind: BS.chip, key, side: BS.chip === "part" ? side : undefined};
    const padEl = ev.target.closest && ev.target.closest("[data-pad]"); if (BS.chip === "pad" && padEl) t.pad = padEl.dataset.pad;
    setTarget(t); if (BS.chip === "pad" && t.pad) askOffers();
    ev.stopPropagation();
  } else if (key && !BS.subj.length) clickRow(key, ev);
}, true);

// ---------------------------------------------------------------- keys
document.addEventListener("keydown", e => {
  if (!(e.ctrlKey || e.metaKey) || !hasScript() || !(S.tab === "build" || document.body.dataset.nv === "build")) return;
  if (e.target.matches && e.target.matches("input, textarea, select")) return;
  if (e.key === "z" && !e.shiftKey) { e.preventDefault(); undo(); } else if ((e.key === "z" && e.shiftKey) || e.key === "y") { e.preventDefault(); redo(); }
});

// ---------------------------------------------------------------- the page's events
const ev = (name, f) => es.addEventListener(name, e => { try { f(JSON.parse(e.data)); } catch (x) { console.error(x); } });
ev("build", d => {
  if (BS.st) { BS.st.phase = d.state === "facts" || d.state === "no_layout" ? BS.st.phase : d.state; if (d.text != null) BS.st.text = d.text; if (d.tail != null) BS.st.tail = d.tail; }
  const p = q("#bld-prog"); if (p) p.textContent = d.text || "";
  if (d.state === "ready" || d.state === "error" || d.state === "no_layout" || d.state === "facts") refreshState().then(() => { if (d.state !== "working") refreshParts(); });
});
ev("applied", () => { drawButtons(); if (BS.st) { refreshState(); refreshParts(); } });
ev("finished", () => { if (BS.st && hasScript()) refreshParts().then(() => { if (BS.pendingTurn) { const k = BS.pendingTurn; BS.pendingTurn = null; BS.subj = [k]; drawTab(); loadTurns(k); } }); });
ev("switched", () => { BS.parts = null; BS.subj = []; BS.target = null; BS.offers = null; setTimeout(async () => { await refreshState(); drawAll(); if (hasScript()) { try { goTab("build"); } catch (e) { /* narrow screens use the bar */ } } }, 50); });

// a Build button in the header opens the tab (and the flow for a new board is the start view's)
// In Build, the findings "no declaration places it" are the unplaced items of a half-built board: they are counted in the parts list and
// folded out of the findings view (they stay in the run record), so a board being built is not a wall of warnings.
const UNDECLARED = /no declaration places it/;
function foldUnplaced() {
  const el = q("#tab-findings");
  if (!el || !BS.parts || !hasScript()) return;
  let n = 0;
  qa(".row", el).forEach(r => { if (UNDECLARED.test(r.textContent)) { r.style.display = "none"; n++; } });
  qa(".gh", el).forEach(g => { let next = g.nextElementSibling, shown = 0; while (next && !next.classList.contains("gh")) { if (next.style.display !== "none") shown++; next = next.nextElementSibling; } g.style.display = shown ? "" : "none"; });
  let note = q("#bld-fold", el);
  if (n && !note) { note = document.createElement("div"); note.id = "bld-fold"; note.className = "bld-note"; note.style.padding = "6px 12px"; el.insertBefore(note, el.firstChild); }
  if (note) { note.textContent = n ? n + " finding(s) \"no declaration places it\" are counted as unplaced in the Build tab" : ""; note.style.display = n ? "" : "none"; }
  const em = q('[data-count="findings"]');
  if (em && n) { const v = Math.max(0, (parseInt(em.textContent, 10) || 0) - n); em.textContent = v || ""; em.style.display = v ? "" : "none"; }
}
const _render = render;
render = function (parts) { _render(parts); if (parts.includes("all") || parts.includes("status")) { drawButtons(); drawTimeline(); } if (parts.includes("all") || parts.includes("findings") || parts.includes("counts")) foldUnplaced(); };
refreshState().then(refreshParts);
})();
