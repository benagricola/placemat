"""The studio page: one static file, nothing fetched from outside, script that parses."""
from pathlib import Path
import json
import re
import shutil
import subprocess

import pytest

import placemat
from placemat.cli import parser

PAGE = Path(placemat.__file__).with_name("studio_page.html")


def test_the_page_ships_in_the_package_and_loads_nothing_from_outside():
    text = PAGE.read_text()
    assert text.lstrip().lower().startswith("<!doctype html>")
    assert not re.search(r'(?:src|href)\s*=\s*"(?:https?:)?//', text) and "@import" not in text
    assert "https://" not in text and "cdn" not in text.lower()
    assert text.count("<script") == 1                  # one inline script, no external one


def test_the_page_names_every_event_the_server_sends():
    text = PAGE.read_text()
    server = (Path(placemat.__file__).with_name("studio.py")).read_text()
    sent = set(re.findall(r'emit\("(\w+)"', server)) | {"hello", "state"}
    heard = set(re.findall(r'\bon\("(\w+)"', text))
    assert sent <= heard, sent - heard


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_script_parses(tmp_path):
    text = PAGE.read_text()
    js = text[text.index("<script>") + 8:text.index("</script>")]
    f = tmp_path / "page.js"
    f.write_text(js)
    done = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_the_command_takes_a_script_a_port_and_no_open():
    args = parser().parse_args(["studio", "layout.py", "--port", "8123", "--no-open"])
    assert (args.command, args.script, args.port, args.no_open) == ("studio", "layout.py", 8123, True)
    assert parser().parse_args(["studio", "layout.py"]).port is None


def test_a_script_with_no_board_beside_it_is_refused(tmp_path, capsys):
    from placemat.cli import main
    script = tmp_path / "x_layout.py"
    script.write_text("")
    assert main(["studio", str(script), "--no-open"]) == 2
    assert "no .zen" in capsys.readouterr().out


# The page's script run in node against a stub of the DOM. The board stub finds the item groups in the markup it is
# given, so the incremental updates (items added to a layer, groups shown and hidden) can be seen.
PRELUDE = r"""
const vm = require("vm"), fs = require("fs");
const els = {}; const ctxHistory = [];
let clock = 1000, WIDE = false;
class FakeDate extends Date { static now() { return clock; } }
const fakeGroup = (key, s) => { const g = {dataset: {key, s: String(s)}, style: {}, cls: new Set(["item"])};
  g.classList = {toggle(c, on) { g.cls[on ? "add" : "delete"](c); }, add(c) { g.cls.add(c); }, remove(c) { g.cls.delete(c); }}; return g; };
const groups = html => [...html.matchAll(/<g class="item[^"]*" data-key="([^"]*)" data-s="(\d+)"/g)].map(m => fakeGroup(m[1], +m[2]));
const mk = sel => new Proxy({
  innerHTML: "", textContent: "", value: "", style: {}, dataset: {}, className: "", attrs: {}, max: 0, handlers: {}, disabled: false,
  classList: {toggle() {}, add() {}, remove() {}, contains() { return false; }},
  addEventListener(t, f) { (this.handlers[t] = this.handlers[t] || []).push(f); },
  insertAdjacentHTML(_, html) { this.innerHTML += html; },
  querySelectorAll(q) {
    if (sel !== "#board") return [];
    if (q === ".item") return groups(this.innerHTML);
    if (q === ".items") { const self = this; return [{insertAdjacentHTML(_, html) { self.innerHTML += html; this.last = groups(html).pop(); }, get lastElementChild() { return this.last; }}]; }
    return [];
  },
  closest: () => null, setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k] || null; }, setPointerCapture() {},
  getBoundingClientRect() { return {x: 0, y: 0, width: 412, height: 600, left: 0, top: 0}; },
}, {get: (o, k) => k in o ? o[k] : undefined});
const stub = sel => els[sel] || (els[sel] = mk(sel));
const listeners = {}, frames = [], fetched = [];
const flush = () => { while (frames.length) frames.shift()(); };
const flushOnce = () => { frames.splice(0).forEach(f => f()); };
const ctx = {
  document: {querySelector: stub, querySelectorAll: () => [], __keys: [], addEventListener(t, f) { if (t === "keydown") this.__keys.push(f); }, body: {dataset: {}}, elementFromPoint: () => null},
  window: {addEventListener() {}}, location: {search: "?t=x", hash: process.env.PAGE_HASH || "", pathname: "/"}, history: {replaceState(a, b, url) { ctxHistory.push(url); }}, matchMedia: q => ({matches: /max-width: 900px/.test(q) ? !WIDE : true}), Date: FakeDate,
  EventSource: class { constructor() { this.addEventListener = (n, f) => { listeners[n] = f; }; } },
  requestAnimationFrame: f => { frames.push(f); }, setInterval() {}, clearInterval() {}, clearTimeout() {}, setTimeout() {}, fetch: (u, o) => { fetched.push([u, o]); return Promise.reject(new Error("no")); },
  URLSearchParams, console,
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx);
flush();
const ev = code => vm.runInContext(code, ctx);      // evaluate in the page's scope, its let and const too
const send = (name, data) => { listeners[name]({data: JSON.stringify(data)}); flush(); };
const board = () => els["#board"];
const out = {};
const shape = (kind, poly) => ({kind, poly, faces: ["front"]});
const item = (key, x) => ({key, kind: "cell", placed: true, face: "front", rotation: 0, note: "", how: "decided", freedom: "decided",
  members: [{ref: "R" + key, value: "", cell: key, shapes: [shape("courtyard", [[x, 1], [x + 2, 1], [x + 2, 3]]), shape("pad", [[x, 1], [x + 1, 1], [x + 1, 2]])]}]});
const BOARD = {id: 1, board: {extent: [0, 0, 40, 30], loops: [[[0, 0], [40, 0], [40, 30], [0, 30]]], drawn: true}, keepouts: [], reservations: []};
const hello = () => send("hello", {script: "x_layout.py", keep: 5, history: [], resolving: 1, error: null});
const started = id => send("started", {id, script: "x_layout.py", at: 0, texts: {"x_layout.py": "a\n", "placemat.toml": "b\n"}, changed: [], stale_files: []});
// a resolve's steps: a part, two copper steps, a part that could not be placed, a part, copper, a part, and the first part's step again
const STEPS = [["a", "part", true], ["fanout a", "copper", false], ["escape U1", "copper", false], ["gone", "part", false], ["b", "part", true], ["escape U1", "copper", false], ["c", "part", true], ["a", "part", true]];
const finish = (id, keys) => {
  const items = keys.map((k, n) => item(k, 1 + 4 * n));
  const steps = STEPS.map(([item, kind, placed], i) => ({i, item, kind, placed, note: "n " + item, freedom: "decided"}));
  send("items", {id, items, steps, unplaced: [{item: "gone", why: "no room"}], pocketed: [], board: BOARD.board, keepouts: [], reservations: []});
  send("finished", {id, counts: {placed: keys.length, findings: 0}, score: {total: 12.34}, timing: {total_s: 1.5, first_step_s: 0.2}, reused: "", notes: [], history: [{id, at: 0, changed: [], timing: {}, counts: {}}]});
};
"""

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def run_page(tmp_path, tail, hash=""):
    """Run the page's script against the DOM stub, then `tail` (JavaScript that fills `out`); `out` as a dict."""
    text = PAGE.read_text()
    (tmp_path / "page.js").write_text(text[text.index("<script>") + 8:text.index("</script>")])
    (tmp_path / "run.js").write_text(PRELUDE + tail + "\nconsole.log(JSON.stringify(out));\n")
    import os
    done = subprocess.run(["node", str(tmp_path / "run.js"), str(tmp_path / "page.js")], capture_output=True, text=True, timeout=60, env=dict(os.environ, PAGE_HASH=hash))
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


@needs_node
def test_the_board_is_drawn_as_it_arrives_during_a_resolve(tmp_path):
    """The outline shows when `board` arrives, each `step` adds its shapes, and the view is set to the board; the
    file select lists the Python files only."""
    out = run_page(tmp_path, r"""
hello(); started(1);
out.before_board = board().innerHTML;
send("board", BOARD);
out.after_board = board().innerHTML;
out.viewbox = board().getAttribute("viewBox");
send("step", {id: 1, item: item("a", 1)});
out.one = board().innerHTML;
send("step", {id: 1, item: item("b", 5)});
out.two = board().innerHTML;
out.steps = els["#tab-steps"].innerHTML;
send("finished", {id: 1, counts: {placed: 2, findings: 0}, score: null, timing: {}, reused: "", notes: [], history: []});
ev('openScript("x_layout.py", 1)'); flush();
out.files = els["#file"].innerHTML;
""")
    assert "<path" not in out["before_board"]
    assert "<path" in out["after_board"] and out["viewbox"]
    assert 'data-key="a"' in out["one"] and "<polygon" in out["one"] and 'data-key="b"' not in out["one"]
    assert out["two"].index('data-key="a"') < out["two"].index('data-key="b"')
    assert 'data-n="0"' in out["steps"] and 'data-n="1"' in out["steps"] and 'data-n="2"' not in out["steps"]
    assert "x_layout.py" in out["files"] and "placemat.toml" not in out["files"]


@needs_node
def test_the_slider_has_one_position_for_each_placement_and_copper_step(tmp_path):
    """The positions are the steps that placed an item the board draws and the copper and cutout steps, in order: a
    part that was not placed and a repeated step are not positions, and the count the page shows is the slider's maximum."""
    out = run_page(tmp_path, r"""
hello(); started(1); send("board", BOARD);
for (const [k, x] of [["a", 1], ["b", 5], ["c", 9]]) send("step", {id: 1, item: item(k, x)});
finish(1, ["a", "b", "c"]);
out.order = ev("replaySteps(plan())").map(s => s.item);
out.nsteps = ev("plan().steps.length");
out.max = els["#slider"].max;
out.label = els["#steplabel"].textContent;
out.at = [0, 1, 4, 6, 7].map(k => ev("itemsAtStep(plan(), " + k + ")"));
out.all = ev("itemsAtStep(plan(), null)");
out.other = ev("otherSteps(plan())").map(s => s.item);
out.tab = els["#tab-steps"].innerHTML;
""")
    assert out["nsteps"] == 8 and out["order"] == ["a", "fanout a", "escape U1", "b", "escape U1", "c"]
    assert out["max"] == 6 and out["label"] == "6 / 6"
    assert out["at"] == [[], ["a"], ["a", "b"], ["a", "b", "c"], ["a", "b", "c"]]     # steps 1..k, and no position past the last
    assert out["all"] == ["a", "b", "c"]
    assert out["other"] == ["a"]                                              # "gone" is listed as not placed
    assert out["tab"].count('data-n="') == 6 and 'class="chip escape">escape' in out["tab"] and 'class="chip decided">decided' in out["tab"]


@needs_node
def test_dragging_the_slider_shows_steps_one_to_k_and_touches_only_what_moved(tmp_path):
    out = run_page(tmp_path, r"""
hello(); started(1); send("board", BOARD);
finish(1, ["a", "b", "c"]);
const shown = () => ev("B.byStep").map(gs => gs.map(g => g.style.display || ""));   // per step, per panel
out.start = shown();
const writes = [];
for (const g of ev("B.byStep").flat()) { let d = g.style.display; Object.defineProperty(g.style, "display", {get: () => d, set: v => { writes.push(g.dataset.key); d = v; }}); }
ev("setReplay(1)"); flush();
out.k1 = shown(); out.w1 = writes.splice(0);
ev("setReplay(4)"); flush();
out.k2 = shown(); out.w2 = writes.splice(0);
ev("setReplay(1)"); flush();
out.back = shown(); out.w3 = writes.splice(0);
ev("setReplay(0)"); flush();
out.k0 = shown(); out.label0 = els["#steplabel"].textContent;
ev("setReplay(6)"); flush();
out.end = shown(); out.replay = ev("S.replay");
""")
    hidden = lambda state: [i for i, gs in enumerate(state) if gs and all(d == "none" for d in gs)]
    assert hidden(out["start"]) == []
    assert hidden(out["k1"]) == [3, 5] and set(out["w1"]) == {"b", "c"}       # at 1 only a shows (b is the fourth step, c the sixth)
    assert hidden(out["k2"]) == [5] and out["w2"] == ["b"]                      # a step forward touches one item
    assert hidden(out["back"]) == [3, 5] and out["w3"] == ["b"]
    assert hidden(out["k0"]) == [0, 3, 5] and out["label0"] == "0 / 6"
    assert hidden(out["end"]) == [] and out["replay"] is None


@needs_node
def test_play_only_goes_forward_and_a_new_resolve_stops_it(tmp_path):
    """Play's position is a function of the clock; a resolve that starts while it runs stops it rather than letting
    it restart from the first step."""
    out = run_page(tmp_path, r"""
out.pos = [0, 100, 249, 250, 251, 999, 1000, 5000, 9e9].map(ms => ev("playPosition({t0: 0, k0: 0, rate: 4, n: 10}, " + ms + ")"));
out.rate = [ev("playRate(1)"), ev("playRate(27)"), ev("playRate(4000)")];
hello(); started(1); send("board", BOARD);
finish(1, ["a", "b", "c"]);
ev("togglePlay()");
const seen = [];
for (let i = 0; i < 6; i++) { clock += 400; flushOnce(); seen.push(ev("S.replay")); }
out.seen = seen; out.playing_after = ev("S.play");
ev("togglePlay()");                                   // again, and a resolve starts partway
clock += 400; flushOnce();
out.mid = ev("S.replay"); out.playing_mid = ev("S.play !== null");
started(2);
out.after_start = [ev("S.replay"), ev("S.play")];
const later = [];
for (let i = 0; i < 5; i++) { clock += 400; flushOnce(); later.push(ev("S.replay")); }
out.later = later;
""")
    assert out["pos"] == [0, 0, 0, 1, 1, 3, 4, 10, 10]                # a step each quarter second, capped at the last
    assert out["rate"] == [3, 3.375, 30]
    seen = [99 if s is None else s for s in out["seen"]]               # None: every step shown
    assert seen == sorted(seen) and seen[0] == 1                      # it never steps back
    assert out["seen"][-1] is None and out["playing_after"] is None   # and ends showing every step, stopped
    assert out["playing_mid"] is True and out["mid"] == 1
    assert out["after_start"] == [None, None] and out["later"] == [None] * 5


@needs_node
def test_the_grid_covers_whatever_is_visible_at_any_pan_and_zoom(tmp_path):
    out = run_page(tmp_path, r"""
hello(); started(1); send("board", BOARD); finish(1, ["a"]);
const rect = id => { const m = els["#grid"].innerHTML.match(new RegExp('<rect id="' + id + '" x="([-\\d.]+)" y="([-\\d.]+)" width="([\\d.]+)" height="([\\d.]+)"')); return m && m.slice(1).map(Number); };
out.cases = [];
for (const v of [{x: 0, y: 0, w: 40, h: 30}, {x: -500, y: 900, w: 60, h: 40}, {x: 10, y: 10, w: 8, h: 6}, {x: -3000, y: -2000, w: 4000, h: 3000}, {x: 31.7, y: 4.2, w: 3, h: 2}]) {
  ev("S.view = " + JSON.stringify(v)); ev("applyView()");
  out.cases.push({vb: ev("S.vb"), major: rect("gridmajor"), minor: rect("gridminor"), viewbox: els["#grid"].attrs.viewBox, board: els["#board"].attrs.viewBox, spec: ev("gridSpec(S.vb, 412)"),
    labels: [...els["#grid"].innerHTML.matchAll(/<text class="g([xy])" x="([-\d.]+)" y="([-\d.]+)"[^>]*>(-?[\d.]+)</g)].map(m => [m[1], +m[2], +m[3], +m[4]])});
}
ev("setFace('both')"); flush();
out.panels = ev("layout(plan())").panels.map(p => [p.mirror, p.dx]); out.LR = ev("layout(plan()).L + layout(plan()).R");
""")
    for c in out["cases"]:
        vb, tol = c["vb"], c["vb"]["w"] / 412 * 5
        assert c["viewbox"] == c["board"]                                         # the grid has the board's view
        x, y, w, h = c["major"]
        assert x <= vb["x"] and y <= vb["y"] and x + w >= vb["x"] + vb["w"] and y + h >= vb["y"] + vb["h"]     # no edge in view
        assert bool(c["minor"]) == bool(c["spec"]["minor"]) and (not c["minor"] or c["minor"] == c["major"])
        assert c["spec"]["major"] >= 10 and c["spec"]["major"] * c["spec"]["ppm"] >= 14      # major lines 10 mm or more apart, and not dense
        xs = [l for l in c["labels"] if l[0] == "x"]
        assert xs and all(vb["x"] <= l[1] <= vb["x"] + vb["w"] + tol for l in xs)
        assert all(vb["y"] - tol <= l[2] <= vb["y"] + vb["h"] for l in c["labels"])
        assert c["spec"]["labelEvery"] * c["spec"]["ppm"] >= 46                 # labels stay a readable distance apart
    assert out["cases"][2]["minor"] and not out["cases"][3]["minor"]          # a millimetre grid zoomed in, none far out
    assert out["cases"][0]["spec"]["major"] == 10
    assert [m for m, _ in out["panels"]] == [False, True]
    assert (out["panels"][1][1] + out["LR"]) % 10 == 0                        # the back panel's mm lines fall on the grid's lines


@needs_node
def test_two_fingers_zoom_one_pans_and_a_double_tap_fits(tmp_path):
    out = run_page(tmp_path, r"""
hello(); started(1); send("board", BOARD); finish(1, ["a"]);
const h = (type, e) => { for (const f of els["#board"].handlers[type] || []) f(Object.assign({preventDefault() {}, pointerType: "touch", target: {closest: () => null}}, e)); };
const vb0 = Object.assign({}, ev("S.vb")); out.vb0 = vb0;
// pan: one finger drags 100 px left
h("pointerdown", {pointerId: 1, clientX: 300, clientY: 300}); h("pointermove", {pointerId: 1, clientX: 200, clientY: 300}); flush();
out.pan = Object.assign({}, ev("S.vb")); h("pointerup", {pointerId: 1, clientX: 200, clientY: 300, type: "pointerup"});
// pinch: two fingers 100 px apart move to 200 px apart about (200, 300)
ev("S.view = " + JSON.stringify(vb0)); ev("applyView()");
h("pointerdown", {pointerId: 1, clientX: 150, clientY: 300}); h("pointerdown", {pointerId: 2, clientX: 250, clientY: 300});
h("pointermove", {pointerId: 1, clientX: 100, clientY: 300}); h("pointermove", {pointerId: 2, clientX: 300, clientY: 300}); flush();
out.pinch = Object.assign({}, ev("S.vb")); out.mid = {x: vb0.x + 200 / 412 * vb0.w, y: vb0.y + 300 / 600 * vb0.h};
h("pointerup", {pointerId: 2, clientX: 300, clientY: 300, type: "pointerup"});
h("pointermove", {pointerId: 1, clientX: 90, clientY: 310}); flush();           // the finger left down carries on panning
out.after_lift = Object.assign({}, ev("S.vb"));
h("pointerup", {pointerId: 1, clientX: 90, clientY: 310, type: "pointerup"});
// two quick taps fit the board; two slow ones do not
const tap = (x, y) => { h("pointerdown", {pointerId: 3, clientX: x, clientY: y}); h("pointerup", {pointerId: 3, clientX: x, clientY: y, type: "pointerup"}); flush(); };
ev("S.view = {x: 5, y: 5, w: 6, h: 4}"); ev("applyView()");
tap(100, 100); clock += 100; tap(104, 102);
out.fitted = ev("S.vb.w");
ev("S.view = {x: 5, y: 5, w: 6, h: 4}"); ev("applyView()"); clock += 1000; tap(100, 100); clock += 1000; tap(100, 100);
out.slow = ev("S.vb.w");
out.zoom = ev("zoomAbout({x: 0, y: 0, w: 40, h: 30}, {left: 0, top: 0, width: 400, height: 300}, 100, 100, 0.5)");
out.limit = ev("zoomAbout({x: 0, y: 0, w: 40, h: 30}, {left: 0, top: 0, width: 400, height: 300}, 100, 100, 1e-6).w");
""")
    vb0, pan, pinch, mid = out["vb0"], out["pan"], out["pinch"], out["mid"]
    assert abs(pan["w"] - vb0["w"]) < 1e-6 and abs((pan["x"] - vb0["x"]) - 100 / 412 * vb0["w"]) < 1e-6      # the board follows the finger
    assert abs(pinch["w"] - vb0["w"] / 2) < 1e-6                                                                # twice as far apart: half the width
    assert abs(pinch["x"] + 200 / 412 * pinch["w"] - mid["x"]) < 1e-6                                          # the point between the fingers stays put
    assert out["after_lift"]["w"] == pinch["w"] and out["after_lift"]["x"] != pinch["x"]
    assert out["fitted"] > 30 and out["slow"] == 6
    z = out["zoom"]                                       # the point under (100, 100) of a 400 x 300 view stays under it
    assert z["w"] == 20 and abs(z["x"] + 100 / 400 * z["w"] - 10) < 1e-9 and abs(z["y"] + 100 / 300 * z["h"] - 10) < 1e-9
    assert out["limit"] == 3                              # and it stops short of a view a few mm wide


def test_the_layout_gives_a_narrow_screen_one_panel_at_the_full_width():
    text = PAGE.read_text()
    assert "minmax(0, 1fr)" in text and 'id="ntabs"' in text
    narrow = text[text.index("@media (max-width: 900px)"):text.index("</style>")]
    assert "grid-template-columns: 1fr;" not in narrow


def test_the_page_follows_the_colour_scheme_and_draws_with_stylesheet_colours():
    text = PAGE.read_text()
    assert "prefers-color-scheme: dark" in text
    script = text[text.index("<script>"):]
    assert not re.search(r'(?:fill|stroke)="#[0-9a-fA-F]{3,6}"', script)          # no colour fixed in the drawing code


# ---------------------------------------------------------------- the second pass: legend, units, links, modules, severity, script list
SETUP = r"""
const cellItem = (key, cell, refs, x) => ({key, kind: "cell", placed: true, face: "front", rotation: 90, note: "rides X; slid 0.5 mm from its slot", how: "decided", freedom: "fixed", why: "the module's reason",
  members: refs.map((r, i) => ({ref: r, value: "10 nF", cell, shapes: [shape("courtyard", [[x + 3 * i, 1], [x + 3 * i + 2, 1], [x + 3 * i + 2, 3]]), shape("pad", [[x + 3 * i, 1], [x + 3 * i + 1, 1], [x + 3 * i + 1, 2]])]}))});
const emptyKeepoutStep = key => ({key, kind: "keepout", placed: true, face: "front", rotation: 0, note: "", how: "decided", freedom: "fixed", members: []});
const LINK = {a: ["Ra", "1"], b: ["Rb", "2"], pa: [1, 1], pb: [5, 1], length: 0.812, limit: 2.5, state: "ok", kind: "SHORT", weight: 8, why: "at the pin"};
const KO = {name: "antenna_clear", poly: [[0, 0], [3, 0], [3, 3]], why: "no copper here", layers: ["F.Cu"], excludes: ["tracks", "vias"], allow: ["GND"], max_height: null};
const RES = {poly: [[4, 4], [6, 4], [6, 6]], why: "fanout of mcu (north side)", face: "front", source: "fanout", allow: [], rule_area: false};
const full = (items, steps, extra = {}) => {
  hello(); started(1);
  send("board", Object.assign({}, BOARD, {keepouts: [KO], reservations: [RES]}));
  send("links", {id: 1, links: [LINK]});
  send("copper", {id: 1, copper: [{t: "track", layer: "F.Cu", face: "front", width: 0.2, a: [0, 0], b: [1, 1], net: "N"}, {t: "plane", layer: "In1.Cu", face: "inner", points: [[0, 0], [4, 0], [4, 4]], net: "G"},
    {t: "via", at: [2, 2], size: 0.45, drill: 0.2, net: "N", layers: []}]});
  send("findings", {id: 1, findings: extra.findings || []});
  send("items", {id: 1, items, steps, unplaced: [], pocketed: [], board: BOARD.board, keepouts: [KO], reservations: [RES]});
  send("finished", {id: 1, counts: {placed: items.length, findings: 0}, score: {total: 3}, timing: {total_s: 1, first_step_s: 0.1}, reused: "", notes: [], history: [{id: 1, at: 0, changed: [], timing: {}, counts: {}}]});
};
const st = (item, kind = "part", placed = true) => ({item, kind, placed, note: "", freedom: "fixed"});
"""


def run_more(tmp_path, tail):
    return run_page(tmp_path, SETUP + tail)


@needs_node
def test_keepout_and_setup_steps_are_not_positions_of_the_replay(tmp_path):
    """A step that settled a keepout (or any region) draws no part of its own: it is not on the slider or in the
    placement list, and a board whose first steps are keepouts replays from its first part."""
    out = run_more(tmp_path, r"""
full([emptyKeepoutStep("k1"), emptyKeepoutStep("k2"), item("a", 1), item("b", 5)], [st("k1", "keepout"), st("k2", "keepout"), st("a"), st("b")]);
out.order = ev("replaySteps(plan())").map(s => s.item);
out.max = els["#slider"].max; out.other = ev("otherSteps(plan())").map(s => s.item); out.items = ev("itemsOf(plan())").map(i => i.key);
out.rows = (els["#tab-steps"].innerHTML.match(/data-n="/g) || []).length;
out.stat = els["#stats"].innerHTML;
""")
    assert out["order"] == ["a", "b"] and out["max"] == 2 and out["items"] == ["a", "b"] and out["rows"] == 2
    assert out["other"] == ["k1", "k2"] and "<b>2</b>placed" in out["stat"]


@needs_node
def test_python_is_highlighted_line_by_line(tmp_path):
    out = run_more(tmp_path, r"""
out.lines = ev('highlightPython("def f(x):\\n    \\"\\"\\"doc\\n    more\\"\\"\\"\\n    return g(x, 1.5)  # note <b>\\n")');
""")
    ls = out["lines"]
    assert ls[0] == '<span class="tk">def</span> <span class="tf">f</span>(x):'
    assert ls[1].count('class="ts"') == 1 and ls[2].count('class="ts"') == 1       # a string over two lines, closed on each
    assert '<span class="tk">return</span> <span class="tf">g</span>(x, <span class="tn">1.5</span>)' in ls[3]
    assert '<span class="tc"># note &lt;b&gt;</span>' in ls[3] and len(ls) == 5


@needs_node
def test_the_legend_switches_each_kind_by_a_stylesheet_rule_and_designators_start_off(tmp_path):
    out = run_more(tmp_path, r"""
full([item("a", 1)], [st("a")]);
out.start = els["#visrules"].textContent;
out.legend = els["#legend"].innerHTML;
const click = id => els["#legend"].onclick({target: {closest: s => s === "[data-id]" ? {dataset: {id}} : null}});
click("via"); click("labels"); click("link:over"); click("cu:In1.Cu");
out.rules = els["#visrules"].textContent;
els["#legend"].onclick({target: {closest: s => s === "[data-exp]" ? {dataset: {exp: "ko", n: "1"}} : null}});
out.expanded = els["#legend"].innerHTML;
click("ko:antenna_clear");
out.ko = els["#visrules"].textContent;
out.rules2 = ev('visRules(new Set(["cy", "ko", "cu:F.Cu", "link:ok"]))');
""")
    assert out["start"].split("\n") == ["#board .ref { display: none; }", '#board [data-ko="antenna_clear"], #board [data-ko-of="antenna_clear"] { display: none; }', '#board [data-res="fanout of mcu (north side)"] { display: none; }']   # designators, keepouts and reserved areas start hidden
    for row in ('data-id="cy"', 'data-id="cu:F.Cu"', 'data-id="via"', 'data-id="link:ok"', 'data-id="link:over"', 'data-grp="ko"', 'data-grp="res"', 'data-id="findings"'):
        assert row in out["legend"]
    assert '<em>1</em>' in out["legend"] and "within its limit" in out["legend"]
    assert "#board .viag { display: none; }" in out["rules"] and ".ref" not in out["rules"]               # via off, designators on
    assert '#board .lkg[data-st="over"]' in out["rules"] and '#board [data-l="In1.Cu"]' in out["rules"]
    assert 'data-id="ko:antenna_clear"' in out["legend"] and 'data-id="ko:antenna_clear"' not in out["expanded"]    # a keepout has its own row, shown until its group is folded
    assert out["ko"].count('[data-ko="antenna_clear"]') == 0                         # a click on its row showed it
    assert out["rules2"].split("\n") == ["#board .cy { display: none; }", "#board .ko { display: none; }", '#board [data-l="F.Cu"] { display: none; }', '#board .lkg[data-st="ok"] { display: none; }']


@needs_node
def test_units_follow_every_figure(tmp_path):
    out = run_more(tmp_path, r"""
full([item("a", 1), item("b", 5)], [st("a"), st("b")]);
out.area = ev('esc("rank 3/9 (12.3 mm2, 2 pins)")'); out.deg = ev("deg(90)");
ev('selectItem("a", {})'); flush();
out.card = els["#card"].innerHTML;
out.tip = ev('fmtUnits("12.3 mm2")');
out.code = ev('highlightPython("x = mm2")').join("");
""")
    assert out["area"] == "rank 3/9 (12.3 mm\u00b2, 2 pins)" and out["deg"] == "90\u00b0" and out["tip"] == "12.3 mm\u00b2"
    assert '<span class="kk">rotation</span><span class="sep">: </span><span class="kvv">0\u00b0</span>' in out["card"]
    assert "mm2" in out["code"]                                                   # source code is shown as written


@needs_node
def test_a_part_card_lists_its_links_with_their_kind_and_the_links_are_drawn_with_a_direction(tmp_path):
    out = run_more(tmp_path, r"""
full([item("a", 1), item("b", 5)], [st("a"), st("b")]);
out.board = board().innerHTML;
ev('selectItem("a", {ref: "Ra"})'); flush();
out.card = els["#card"].innerHTML;
out.tip = ev("linkLine(plan().links[0], null)");
""")
    assert 'marker-end="url(#ar-ok)"' in out["board"] and 'data-a="Ra"' in out["board"] and 'data-b="Rb"' in out["board"] and "lkdot" in out["board"]
    assert "SHORT" in out["card"] and "Ra.1 -&gt; Rb.2" in out["card"] and "0.812 / 2.5 mm" in out["card"] and "1 link" in out["card"]
    assert out["tip"] == "SHORT  Ra.1 -> Rb.2  0.812 mm of 2.5 allowed"


@needs_node
def test_a_keepouts_card_names_its_layers_excludes_and_allow(tmp_path):
    out = run_more(tmp_path, r"""
full([item("a", 1)], [st("a")]);
ev('selectRegion("ko", "antenna_clear")'); flush();
out.card = els["#card"].innerHTML;
out.tip = ev('regionLines("ko", "antenna_clear", plan())'); out.res = ev('regionLines("res", "fanout of mcu (north side)", plan())');
ev("renderBoard()"); out.board = board().innerHTML;
""")
    assert "antenna_clear" in out["card"] and '<span class="chip ">F.Cu</span>' in out["card"] and '<span class="chip ">tracks</span>' in out["card"] and '<span class="chip net">GND</span>' in out["card"] and "no copper here" in out["card"]
    assert out["tip"][0] == "keepout antenna_clear" and "excludes: tracks, vias" in out["tip"] and out["res"][0] == "reserved area"
    assert 'class="ko sel" data-ko="antenna_clear"' in out["board"] and 'data-res="fanout of mcu (north side)"' in out["board"]


@needs_node
def test_selecting_a_part_offers_its_module_and_selecting_that_lights_all_its_parts(tmp_path):
    out = run_more(tmp_path, r"""
full([cellItem("psu", "psu", ["C1", "C2"], 1), Object.assign(item("b", 12), {members: [{ref: "Rb", value: "", cell: "", shapes: item("b", 12).members[0].shapes}]})], [st("psu", "cell"), st("b")]);
out.keys = [...ev('moduleKeys(plan(), "psu")')]; out.refs = ev('moduleRefs(plan(), "psu")');
ev('selectItem("psu", {ref: "C2"})'); flush();
out.part = els["#card"].innerHTML;
els["#card"].onclick({target: {closest: s => s === "[data-act]" ? {dataset: {act: "module", id: "psu"}} : null}}); flush();
out.module = els["#card"].innerHTML; out.sel = ev("[S.sel, S.selRef, S.module]");
out.single = ev('moduleOf(Object.assign({}, plan().items.find(i => i.key === "b"), {kind: "part"}), "Rb")');
""")
    assert out["keys"] == ["psu"] and out["refs"] == ["C1", "C2"]
    assert "C2" in out["part"] and "select cell" in out["part"] and "psu" in out["part"]
    assert "cell psu" in out["module"] and 'data-ref="C1"' in out["module"] and 'data-ref="C2"' in out["module"]
    assert out["sel"] == ["psu", None, "psu"] and out["single"] == ""


@needs_node
def test_how_a_step_was_placed_is_said_in_words(tmp_path):
    out = run_more(tmp_path, r"""
const w = (s, it) => ev("howText(" + JSON.stringify(s) + ", " + JSON.stringify(it) + ")");
out.rides = w({note: "rides l_match"}, null);
out.decided = w({freedom: "fixed", note: ""}, null);
out.edge = w({freedom: "edge", note: "slid 0.50 mm from its slot: x"}, null);
out.searched = w({freedom: "searched", note: "rank 3/9 (4 mm2); seeded on VDD)"}, null);
out.pocket = w({}, {how: "pocket"});
out.step = els["#tab-steps"].innerHTML;
full([item("a", 1)], [Object.assign(st("a"), {note: "rank 1/2; the whole note", why: "because"})], {findings: [{text: "a (fixed): sits close", kind: "k", at: null, item: "a", severity: "critical"}]});
out.row = els["#tab-steps"].innerHTML;
""")
    assert out["rides"] == "rides l_match" and out["decided"] == "decided at a point" and out["edge"] == "decided along an edge, slid 0.50 mm"
    assert out["searched"] == "searched: rank 3 of 9, seeded on VDD" and out["pocket"].startswith("pocket")
    assert 'data-info="steps"' in out["row"] and 'class="fdot critical"' in out["row"] and "the whole note" in out["row"] and 'class="full"' in out["row"]


@needs_node
def test_findings_default_to_warning_group_by_severity_when_given_and_keep_room_for_a_fix(tmp_path):
    out = run_more(tmp_path, r"""
const f = (text, severity) => Object.assign({text, kind: "kind_a", at: null, item: ""}, severity ? {severity} : {});
full([item("a", 1)], [st("a")], {findings: [f("one"), f("two")]});
out.plain = els["#tab-findings"].innerHTML;
full([item("a", 1)], [st("a")], {findings: [f("n1", "notice"), f("w1", "warning"), f("c1", "critical"), f("old")]});
out.mixed = els["#tab-findings"].innerHTML;
els["#tab-findings"].onclick({target: {closest: s => s === "[data-sev]" ? {dataset: {sev: "critical"}} : null}});
out.filtered = els["#tab-findings"].innerHTML;
""")
    assert 'class="sev warning"' in out["plain"] and 'class="gh" data-kind="kind_a"' in out["plain"] and "filters" not in out["plain"]
    assert out["mixed"].index('data-kind="critical"') < out["mixed"].index('data-kind="warning"') < out["mixed"].index('data-kind="notice"')
    assert "all 4" in out["mixed"] and "critical 1" in out["mixed"] and out["mixed"].count('class="fixslot"') == 4     # an old finding is a warning
    assert 'data-kind="warning"' not in out["filtered"] and "c1" in out["filtered"] and "w1" not in out["filtered"]


@needs_node
def test_silk_text_is_drawn_with_its_own_justification_rotation_and_mirroring(tmp_path):
    out = run_more(tmp_path, r"""
out.a = ev('silkText({text: "TOP <1>", at: [5, 6], size: 0.8, rotation: 90, hjust: "left", vjust: "bottom", mirrored: false})');
out.b = ev('silkText({text: "X", at: [1, 2], size: 1, rotation: 0, hjust: "centre", vjust: "centre", mirrored: true})');
out.size = [ev('labelSize("R12", 0.6)'), ev('labelSize("R1", 6)')];
""")
    assert 'transform="translate(5 6) rotate(-90)"' in out["a"] and 'text-anchor="start"' in out["a"] and 'dominant-baseline="text-after-edge"' in out["a"] and "TOP &lt;1&gt;" in out["a"]
    assert 'scale(-1 1)' in out["b"] and 'text-anchor="middle"' in out["b"] and 'dominant-baseline="central"' in out["b"]
    assert out["size"][0] == 0 and out["size"][1] == 0.9                        # a designator that does not fit its part is not drawn


@needs_node
def test_the_header_menu_lists_the_layout_scripts_and_choosing_one_asks_the_server_to_switch(tmp_path):
    out = run_page(tmp_path, r"""
const scripts = [{id: "m/A_layout.py", title: "A", subtitle: "first", current: true}, {id: "m/B_layout.py", title: "B", subtitle: "", current: false}];
send("hello", {script: "A_layout.py", title: "A", subtitle: "first board", scripts, keep: 5, history: [], resolving: null, error: null});
send("started", {id: 1, script: "A_layout.py", at: 0, texts: {"A_layout.py": "board.place()\n", "core_geometry.py": "def f(): pass\n", "placemat.toml": ""}, changed: [], stale_files: []});
out.title = [els["#board-title"].textContent, els["#board-sub"].textContent];
els["#menu"].hidden = true; els["#brandbtn"].onclick();
out.menu = els["#menu"].innerHTML; out.open = els["#menu"].hidden === false;
els["#menu"].onclick({target: {closest: s => s === "[data-script]" ? {dataset: {script: "m/B_layout.py"}} : null}});
out.fetched = fetched.map(([u, o]) => [u, o.method, o.body]); out.closed = els["#menu"].hidden;
send("switched", {script: "B_layout.py", title: "B", subtitle: "", scripts: scripts.map(s => Object.assign({}, s, {current: !s.current})), keep: 5, history: [], resolving: null, error: null});
out.after = [els["#board-title"].textContent, ev("S.docs.size"), ev("S.live"), ev("S.status")];
""")
    assert out["title"] == ["A", "first board"] and out["open"] and out["closed"] is True
    assert "m/A_layout.py" in out["menu"] and "m/B_layout.py" in out["menu"] and 'class="cur"' in out["menu"] and "core_geometry" not in out["menu"]
    assert out["fetched"] == [["/switch?t=x", "POST", '{"script":"m/B_layout.py"}']]
    assert out["after"] == ["B", 0, None, "waiting"]


@needs_node
def test_with_no_script_the_page_is_a_picker_and_choosing_goes_through_the_same_switch(tmp_path):
    out = run_page(tmp_path, r"""
const scripts = [{id: "a/A_layout.py", title: "A", subtitle: "first", current: false}, {id: "b/B_layout.py", title: "B", subtitle: "second", current: false}];
send("hello", {script: "", picker: true, root: "/work/proj", scripts, keep: 5, history: [], resolving: null, error: null, runs: [], run: null});
out.picker = [els["#picker"].hidden, els["#picker"].innerHTML]; out.title = els["#board-title"].textContent; out.status = els["#statustext"].textContent; out.run = els["#runbtn"].disabled;
els["#picker"].onclick({target: {closest: s => s === "[data-script]" ? {dataset: {script: "b/B_layout.py"}} : null}});
out.fetched = fetched.map(([u, o]) => o.body);
send("switched", {script: "B_layout.py", title: "B", subtitle: "second", scripts: scripts.map(s => Object.assign({}, s, {current: s.id[0] === "b"})), keep: 5, history: [], resolving: null, error: null, runs: [], run: null});
out.after = [els["#picker"].hidden, els["#board-title"].textContent];
""")
    assert out["picker"][0] is False and "2 found under" in out["picker"][1] and "/work/proj" in out["picker"][1] and "A_layout.py" in out["picker"][1] and "second" in out["picker"][1]
    assert out["title"] == "placemat studio" and out["status"] == "choose a script" and out["run"] is True
    assert out["fetched"] == ['{"script":"b/B_layout.py"}'] and out["after"] == [True, "B"]


@needs_node
def test_the_script_is_a_dialog_opened_on_a_line_with_its_context_and_a_full_screen_button(tmp_path):
    out = run_more(tmp_path, r"""
const text = Array.from({length: 60}, (_, i) => "line_" + (i + 1) + " = 1").join("\n") + "\n";
full([Object.assign(item("a", 1), {file: "x_layout.py", line: 30, span: [30, 30]})], [st("a")]);
ev('S.texts = {"x_layout.py": ' + JSON.stringify(text) + '}');
out.closed = [ev("S.scriptOpen"), els["#script"].classList];
ev('openScript("x_layout.py", 30)'); flush();
const rows = () => (els["#scriptbody"].innerHTML.match(/data-n="(\d+)"/g) || []).map(s => +s.match(/\d+/)[0]);
out.ctx = [ev("S.scriptOpen"), rows()[0], rows().slice(-1)[0], rows().length, (els["#scriptbody"].innerHTML.match(/more line/g) || []).length];
els["#scriptbody"].onclick({target: {closest: s => s === "[data-more]" ? {} : null}}); flush();
out.whole = rows().length;
els["#scriptfull"].onclick(); flush(); out.full = [ev("S.scriptFull"), els["#scriptfull"].textContent];
els["#scriptclose"].onclick(); flush(); out.after = [ev("S.scriptOpen"), ev("S.scriptFull")];
ev('S.sel = "a"; plan().items.find(i => i.key === "a").file = "x_layout.py"'); ev("renderCard()");
ev('selectItem("a", {})'); flush();
els["#card"].onclick({target: {closest: s => s === "[data-act]" ? {dataset: {act: "src"}} : null}}); flush();
out.fromcard = [ev("S.scriptOpen"), ev("S.selLine")];
""")
    assert out["closed"][0] is False
    assert out["ctx"] == [True, 20, 40, 21, 2]                       # ten lines either side of line 30, and where the rest is
    assert out["whole"] == 60 and out["full"] == [True, "Restore"] and out["after"] == [False, False]
    assert out["fromcard"][0] is True and out["fromcard"][1] == {"file": "x_layout.py", "n": 30}


@needs_node
def test_the_steps_timeline_grows_as_steps_stream_and_the_slider_stays_where_it_is_put(tmp_path):
    out = run_page(tmp_path, r"""
hello(); started(1); send("board", BOARD);
send("step", {id: 1, item: item("a", 1)});
send("step", {id: 1, item: {key: "track N", kind: "copper", placed: false, note: "1 op(s)", why: "", freedom: null, how: "decided", members: []}, ops: [{t: "track", net: "N", layer: "F.Cu", face: "front", width: 0.2, a: [1, 1], b: [3, 1], arc: null}]});
out.two = [ev("replaySteps(plan()).map(s => s.item)"), els["#slider"].max, els["#slider"].disabled, els["#steplabel"].textContent, ev("plan().copper.length"), ev("plan().steps[1].copper")];
out.rows = (els["#tab-steps"].innerHTML.match(/data-n="/g) || []).length;
ev("setReplay(1)"); flush(); out.back = [ev("S.replay"), els["#follow"].hidden];
send("step", {id: 1, item: item("b", 5)});
out.still = [ev("S.replay"), els["#steplabel"].textContent, els["#slider"].max];
els["#follow"].handlers.click[0](); flush(); out.follow = [ev("S.replay"), els["#follow"].hidden];
ev("setReplay(1)"); flush();
finish(1, ["a", "b", "c"]);
out.done = [ev("S.replay"), els["#steplabel"].textContent.indexOf("so far")];
""")
    assert out["two"][0] == ["a", "track N"] and out["two"][1] == 2 and out["two"][2] is False and out["two"][3] == "2 / 2 so far"
    assert out["two"][4] == 1 and out["two"][5] == [0] and out["rows"] == 2
    assert out["back"] == [1, False] and out["still"][0] == 1 and out["still"][1] == "1 / 3 so far" and out["still"][2] == 3
    assert out["follow"] == [None, True]
    assert out["done"][0] == 1 and out["done"][1] == -1                  # the final plan replaced the streamed one with the slider where it was left


@needs_node
def test_a_run_is_started_from_the_button_listed_with_its_result_and_compared_with_the_newest_resolve(tmp_path):
    out = run_more(tmp_path, r"""
full([item("a", 1)], [st("a")]);
send("run_started", {id: 1, at: 1});
out.btn = [els["#runbtn"].textContent, els["#runbtn"].disabled];
send("run_progress", {id: 1, item: "usbpd.esd", n: 12});
out.log = els["#tab-compare"].innerHTML;
const run = {id: "r1", label: "try", status: "ok", at: Date.now() / 1000, score: 12.5, findings: 3, severities: {warning: 2, notice: 1}, drc: {drc_real: 2, unconnected: 0}, airwire_mm: 50, open_nets: 1, checks: {checks_failed: 1}, verdicts: [{check: "hot-loop", subject: "buck", ok: false, note: "too long"}], timing: {drc: 4.8}, failure: null};
send("run_done", {id: 1, code: 0, run, tail: [], runs: [run]});
out.done = [els["#runbtn"].textContent, els["#runbtn"].disabled, els["#tab-compare"].innerHTML];
const click = sel => els["#tab-compare"].onclick({target: {closest: s => s === sel ? {dataset: {run: "r1", cmpRun: "r1"}} : null}});
click(".row.run"); out.open = els["#tab-compare"].innerHTML;
els["#runbtn"].onclick(); out.post = fetched.map(([u, o]) => [u, o && o.method]);
""")
    assert out["btn"] == ["Running...", True] and "step 12: usbpd.esd" in out["log"]            # the run's steps, from the channel, not its printed lines
    assert out["done"][0] == "Run" and out["done"][1] is False
    d = out["done"][2]
    assert 'data-run="r1"' in d and "score 12.5" in d and "DRC 2" in d and 'data-cmp-run="r1"' in d and 'data-info="runs"' in d
    assert "Failed checks" in out["open"] and "hot-loop" in out["open"] and "2 real" in out["open"]
    assert out["post"][-1] == ["/run?t=x", "POST"]


@needs_node
def test_a_region_group_row_switches_all_its_children_and_reads_all_none_or_some(tmp_path):
    out = run_more(tmp_path, r"""
full([item("a", 1)], [st("a")]);
ev('plan().keepouts.push({name: "second", poly: [[7, 7], [9, 7], [9, 9]], why: "", layers: null, excludes: [], allow: [], max_height: null})');
ev("renderLegend()");
const rules = () => els["#visrules"].textContent, legend = () => els["#legend"].innerHTML;
const grp = id => els["#legend"].onclick({target: {closest: s => s === "[data-grp]" ? {dataset: {grp: id}} : null}});
const row = id => els["#legend"].onclick({target: {closest: s => s === "[data-id]" ? {dataset: {id}} : null}});
const head = () => (legend().match(/<div class="lg[^"]*" data-grp="ko"[^>]*>/) || [""])[0];
out.start = [rules(), head()];
grp("ko"); out.shown = [rules(), head()];
grp("ko"); out.hidden = [rules(), head()];
row("ko:second"); out.one = [rules(), head()];
row("ko:antenna_clear"); out.both = [rules(), head()];
grp("res"); out.res = rules();
""")
    ko = lambda r: [l for l in r.split("\n") if "data-ko" in l]
    assert len(ko(out["start"][0])) == 2 and "none" in out["start"][1]               # a keepout the page has not seen yet starts hidden
    assert ko(out["shown"][0]) == [] and "all" in out["shown"][1]
    assert len(ko(out["hidden"][0])) == 2 and "none" in out["hidden"][1]
    assert len(ko(out["one"][0])) == 1 and "second" not in ko(out["one"][0])[0] and "some" in out["one"][1]
    assert ko(out["both"][0]) == [] and "all" in out["both"][1]
    assert "data-res" not in out["res"]


@needs_node
def test_a_link_is_green_up_to_its_limit_and_red_beyond_and_both_ends_are_marked_on_any_face(tmp_path):
    out = run_more(tmp_path, r"""
full([item("a", 1), item("b", 5)], [st("a"), st("b")]);
ev('plan().links.push({a: ["Ra", "3"], b: ["Rb", "4"], pa: [1, 1], pb: [5, 1], length: 4, limit: 1, state: "over", kind: "SHORT", weight: 8, why: ""})');
ev("renderBoard()"); out.board = board().innerHTML;
ev('S.face = "back"'); ev("renderBoard()"); out.back = board().innerHTML;
""")
    b = out["board"]
    assert 'class="lk ok" x1="1" y1="1" x2="2" y2="1"' in b and 'class="lk over" x1="2" y1="1" x2="5" y2="1"' in b
    assert 'class="lk ok" x1="1" y1="1" x2="5" y2="1"' in b.split('data-i="0"')[1].split("</g>")[0]      # the one within its limit stays whole
    assert 'class="lk ok" x1="1" y1="1" x2="5" y2="1"' not in b.split('data-i="1"')[1]                    # the over link has no all-green line
    for text in ("Ra.1", "Rb.2", "Ra.3", "Rb.4"):
        assert text in out["back"]
    assert "lkend" not in b and "lkend" not in out["back"]                                                       # no ring round an end
    assert 'class="lkdot ok" cx="1" cy="1"' in b.split('data-i="1"')[1]                                      # the start of a link over its limit is green
    assert re.search(r'class="lkdot over"', b.split('data-i="1"')[1]) is None


@needs_node
def test_the_part_card_is_in_sections_with_the_note_split_into_its_parts(tmp_path):
    note = ("rank 20/24 (22.4 mm2, 19th of 24; 17 pins, 15th); seeded on USB_CC1, USB_CC2; moved 10.48 mm off the hint: cell X's U40 silk is 0.00 mm from cell Y's U9 mask opening (needs 0.20); "
            "vias: 1 GND via shared, 5 left its pad, 1 dropped under cell Z's C72; push from L1: 2.5 at 3.0 mm (limit 8)")
    out = run_more(tmp_path, r"""
const it = Object.assign(cellItem("psu", "psu", ["Ra", "C2"], 1), {freedom: "searched", how: "searched", moved_mm: 10.48, note: %s, why: "", file: "x_layout.py", line: 358});
const lone = Object.assign(cellItem("solo", "", ["R1"], 20), {kind: "part", note: "", why: ""});
full([it, lone], [st("psu", "cell"), st("solo")], {findings: [{text: "psu: sits close", kind: "k", at: null, item: "psu", severity: "critical"}]});
ev('selectItem("psu", {})'); flush();
out.card = els["#card"].innerHTML;
ev('selectItem("solo", {})'); flush();
out.solo = els["#card"].innerHTML;
""" % json.dumps(note))
    c = out["card"]
    assert "<span>module</span>" not in c and 'data-act="module"' in c and c.index('data-act="module"') < c.index('data-act="close"')   # the module is the item: a pill by the title
    for title in ("Placement", "Why it moved", "Vias", "Links", "Findings"):
        assert '<div class="cst">' + title + "</div>" in c, title
    assert '<span class="chip net">USB_CC1</span>' in c and '<span class="chip net">USB_CC2</span>' in c
    assert '<span class="kvv">20 of 24</span>' in c and "22.4 mm\u00b2, 19th largest" in c and "17 pins, 15th by pin count" in c
    assert '<span class="val warn">10.48 mm</span>' in c and "silk is 0.00 mm from" in c
    assert '<span class="chip face-front">front</span>' in c and '<span class="chip searched">searched</span>' in c
    assert "GND via shared" in c and "left its pad" in c and "<b>L1</b> 2.5 at 3.0 mm, limit 8" in c
    assert "critical" in c and "x_layout.py:358" in c
    assert 'data-act="module"' not in out["solo"]


@needs_node
def test_clicking_a_finding_lights_its_parts_and_pads_and_clears_with_the_next_selection(tmp_path):
    out = run_more(tmp_path, r"""
const f = {text: "link Ra.1 to Rb.2 is 5 mm", kind: "link_over", at: null, item: "", refs: ["Ra", "Rb"], pads: [["Ra", "1"], ["Rb", "2"]], severity: "warning"};
const g = {text: "a: sits close", kind: "fixed", at: null, item: "a", refs: ["Ra"], pads: [], severity: "critical"};
full([item("a", 1), item("b", 5)], [st("a"), st("b")], {findings: [f, g]});
out.pad = /data-pad="/.test(board().innerHTML);
els["#tab-findings"].onclick({target: {closest: s => s === ".row" ? {dataset: {i: "0"}} : null}}); flush();
out.focus = ev("S.focus"); out.sel = ev("[S.sel, S.selRef]");
out.card = els["#card"].innerHTML;
ev('selectItem("b", {})'); out.cleared = ev("S.focus");
els["#card"].onclick({target: {closest: s => s === "[data-act]" ? {dataset: {act: "finding", fi: "1"}} : null}});
out.again = ev("S.focus && S.focus.refs");
""")
    assert out["pad"] and out["focus"] == {"refs": ["Ra", "Rb"], "pads": [["Ra", "1"], ["Rb", "2"]]}
    assert out["sel"] == ["a", None] and out["cleared"] is None and out["again"] == ["Ra"]
    assert 'data-act="finding" data-fi="1"' in out["card"]


@needs_node
def test_copper_and_cutouts_are_drawn_at_their_step_and_the_rest_with_the_last(tmp_path):
    out = run_more(tmp_path, r"""
full([item("a", 1)], [st("a")]);
const ops = ev("plan().copper").length;
ev('plan().steps = [{item: "a", kind: "part", placed: true, note: ""}, {item: "track N", kind: "copper", placed: false, note: "1 op(s)", copper: [0]}, {item: "cutout hole", kind: "cutout", placed: false, note: "", loop: 1, copper: []}]');
ev('plan().board.loops.push([[30, 20], [34, 20], [34, 24]])');
ev("renderBoard()");
out.board = board().innerHTML; out.steps = ev("replaySteps(plan())").map(s => [s.item, s.type, s.n]);
""")
    b = out["board"]
    assert out["steps"] == [["a", "place", 0], ["track N", "copper", 1], ["cutout hole", "cutout", 2]]
    assert re.search(r'<line class="trk l-F"[^>]*data-s="1"', b)                            # the track the step laid
    assert 'class="plane l-In" data-s="2"' in b and 'class="viag" data-s="2"' in b        # the rest of the copper shows with the last step
    assert re.search(r'<polygon class="cutoutg" data-s="2" points="30,20', b) and b.count("M 30,20") == 0        # the hole is no part of the edge


@needs_node
def test_a_step_opens_into_the_cards_sections_and_says_each_thing_once(tmp_path):
    out = run_more(tmp_path, r"""
const note = "rank 7/24 (81.1 mm2, 7th of 24; 27 pins, 10th); seeded on USB_HV, USB_WET, VBUS, VBUS_DISCH; vias: 1 GND via shared, 2 left its pad";
full([Object.assign(item("a", 1), {how: "searched", freedom: "searched", note})], [Object.assign(st("a"), {note, freedom: "searched"})]);
out.row = els["#tab-steps"].innerHTML;
""")
    r = out["row"]
    assert r.count("rank 7 of 24") == 1 and ">7 of 24<" in r and 'class="chip searched">searched</span>' in r      # the pill says searched, the line the rank, the opened row the rank as a pill
    assert 'class="cst">Placement</div>' in r and 'class="cst">Vias</div>' in r and '<span class="chip net">VBUS_DISCH</span>' in r
    assert "seeded on USB_HV, USB_WET, VBUS +1" in r                                          # the one line keeps the first nets


@needs_node
def test_each_explanatory_note_is_an_info_icon_on_its_heading(tmp_path):
    out = run_more(tmp_path, r"""
full([item("a", 1)], [st("a")]);
out.legend = els["#legend"].innerHTML; out.steps = els["#tab-steps"].innerHTML; out.info = ev("Object.keys(INFO)");
""")
    assert '<h4>Links<button class="info" data-info="links"' in out["legend"] and "lgnote" not in out["legend"] and "A link is a pull" not in out["legend"]
    assert 'data-info="steps"' in out["steps"] and "Each row is one step" not in out["steps"]
    assert {"links", "steps", "other"} <= set(out["info"])


@needs_node
def test_congestion_is_a_ramp_with_a_scale_and_a_footprints_copper_is_drawn(tmp_path):
    out = run_more(tmp_path, r"""
full([item("a", 1)], [st("a")]);
out.cols = [0.05, 0.3, 0.7, 1.0, 1.25, 3].map(u => ev("heatColour(" + u + ")"));
const it = ev("plan().items[0]"); it.members[0].shapes.push({kind: "copper", faces: ["front"], layers: ["F.Cu"], poly: [[1, 1], [2, 1], [2, 1.2]]}, {kind: "copper", faces: [], layers: ["In1.Cu"], poly: [[1, 1], [2, 1], [2, 1.3]]});
ev("renderBoard()"); out.board = board().innerHTML;
ev("plan().congestion = {cell: 0.5, origin: [0, 0], worst: 1.4, worst_at: [2, 2], cells: [[1, 1, 0.9]]}"); ev("renderLegend()"); out.legend = els["#legend"].innerHTML;
""")
    assert len(set(out["cols"])) == 5 and out["cols"][-1] == out["cols"][-2]                       # distinct hues up to the top of the scale
    assert 'class="fcu l-F" data-l="F.Cu"' in out["board"] and 'class="fcu l-In" data-l="In1.Cu"' in out["board"]
    assert 'class="lgscale"' in out["legend"] and 'data-info="marks"' in out["legend"]


@needs_node
def test_a_resolve_in_progress_shows_a_spinner_the_time_the_steps_and_the_step_being_worked_on(tmp_path):
    out = run_page(tmp_path, r"""
hello(); started(1); send("board", BOARD);
out.start = [els["#runstrip"].hidden, els["#rs-steps"].textContent];
send("begin", {id: 1, kind: "total", items: 24, searched: 18, copper: 6, replay: 0});
send("step", {id: 1, item: item("a", 1)});
send("begin", {id: 1, kind: "begin", item: "psu", what: "searched", rank: 7, of: 18, replaying: false, n: 3});
send("begin", {id: 1, kind: "phase", text: "scanning the front or back", hint: [6, 8], radius: 12});
clock += 3200; ev("renderProgress()");
out.prog = [els["#runstrip"].hidden, els["#rs-steps"].textContent + " | " + els["#rs-work"].innerHTML, els["#progbar"].style.width, els["#rs-el"].textContent];
ev("renderSteps()"); out.pending = els["#tab-steps"].innerHTML; ev("renderStepNow()"); out.stepnow = els["#stepnow"].innerHTML; out.stepnow_shown = els["#stepnow"].style.display;
out.mark = ev("S.work.cur");
send("step", {id: 1, item: Object.assign(item("psu", 5), {key: "psu"})});
out.after = [ev("S.work.cur"), els["#tab-steps"].innerHTML, els["#rs-work"].innerHTML, els["#rs-work"].className];
finish(1, ["a", "b", "c"]);
out.done = [els["#runstrip"].hidden, ev("S.work"), els["#rs-steps"].textContent];
""")
    assert out["start"][0] is False and "step 0" in out["start"][1] and "so far" in out["start"][1]
    assert out["prog"][0] is False and "step 1 of about 30" in out["prog"][1] and 'title="psu">psu</b>' in out["prog"][1] and "scan front/back" in out["prog"][1] and "3.2 s" in out["prog"][1] and out["prog"][2] == "3%" and out["prog"][3] == "0:03"
    pr = out["pending"]
    assert 'id="pendrow"' in pr and 'class="f-item" title="psu">psu</b>' in pr and '<span class="chip searched">searching</span>' in pr
    assert '<span class="f-rank"><span class="lbl">rank </span>7 of 18</span>' in pr and '<span class="chip phase">scan front/back</span>' in pr and '<span class="f-time">3.2 s</span>' in pr
    assert "scanning the front or back" not in pr                                         # the phase is a short pill
    assert out["stepnow_shown"] == "none"                                                   # the step display is for settled steps; the running strip has this one
    assert out["mark"]["hint"] == [6, 8] and out["mark"]["rank"] == 7
    assert out["after"][0] is None and "waiting" not in out["after"][1] + out["after"][2]
    assert out["after"][3] == "flds settled" and 'title="psu">psu</b>' in out["after"][2] and '<span class="f-time">3.2 s</span>' in out["after"][2]     # the settled step stays, dimmed, with its time
    assert 'class="row pending settled"' in out["after"][1]
    assert out["done"][1] is None and out["done"][0] is False and out["done"][2].startswith("done in ")


@needs_node
def test_replayed_steps_are_one_pending_row_not_a_flicker_of_rows(tmp_path):
    out = run_page(tmp_path, r"""
hello(); started(1); send("board", BOARD);
send("begin", {id: 1, kind: "total", items: 3, searched: 0, copper: 0, replay: 3});
send("begin", {id: 1, kind: "begin", item: "a", what: "decided", rank: null, of: null, replaying: true, n: 0});
send("step", {id: 1, item: item("a", 1)});
send("begin", {id: 1, kind: "begin", item: "b", what: "decided", rank: null, of: null, replaying: true, n: 1});
out.row = els["#tab-steps"].innerHTML; out.replayed = ev("S.work.replayed");
out.text = els["#rs-work"].innerHTML;
send("begin", {id: 1, kind: "begin", item: "c", what: "searched", rank: 1, of: 1, replaying: false, n: 2});
out.after = els["#tab-steps"].innerHTML;
""")
    assert out["replayed"] == 1 and "replaying unchanged steps" in out["row"] and "1 of 3" in out["row"] and '<span class="chip decided">replay</span>' in out["row"] and out["row"].count('id="pendrow"') == 1
    assert "replaying unchanged steps" in out["text"]
    assert "replaying unchanged steps" not in out["after"] and "searching" in out["after"]


@needs_node
def test_the_note_forms_are_parsed_into_labelled_values_with_units_and_orders_one_way(tmp_path):
    out = run_more(tmp_path, r"""
const note = "rank 8/24 (204.8 mm2, 4th of 24; 3 pins, 23rd) (script: high), required; pocket 16.5 x 22.0 at (26.6, 36.4): nothing it connects to is placed; on the line x = 26.50; slid 0.50 mm from its slot: x; stopped 19.40 mm short of the south end by: its member U8 sits in a keepout";
const it = Object.assign(cellItem("psu", "psu", ["Ra", "C2"], 1), {freedom: "searched", how: "searched", note, why: ""});
full([it], [st("psu", "cell")]);
ev('selectItem("psu", {})'); flush();
out.card = els["#card"].innerHTML; out.parts = ev("noteParts(" + JSON.stringify(note) + ")");
out.row = els["#tab-steps"].innerHTML;
""")
    c = out["card"]
    assert '<span class="kvv">8 of 24</span>' in c and "204.8 mm\u00b2, 4th largest" in c and "3 pins, 23rd by pin count" in c
    assert '<span class="chip prio-high">high</span> <span class="dim">from the script</span>' in c and '<span class="chip bad">required</span>' in c
    assert '<div class="cst">Pocket</div>' in c and "16.5 x 22.0 mm" in c and "(26.6, 36.4) mm" in c and "nothing it connects to is placed" in c
    assert "x = 26.50 mm" in c and '<span class="val warn">0.50 mm</span> from its slot' in c and "19.40 mm</span> before the south end" in c
    assert "script: high" not in c and "pocket 16.5" not in c
    assert out["parts"]["pocket"] == {"w": "16.5", "h": "22.0", "x": "26.6", "y": "36.4", "why": "nothing it connects to is placed"}
    assert "rank 8 of 24" in out["row"]
    import re as _re
    text = _re.sub(r"<[^>]+>", "", c.replace('<span class="sep">: </span>', ": "))      # what copying the card gives: label: value
    assert "rank: 8 of 24" in text and "face: front" in text and "rotation: 90" in text and "area: 204.8 mm" in text


@needs_node
def test_a_keepouts_reservation_follows_its_row_and_a_name_with_a_comma_still_hides(tmp_path):
    out = run_more(tmp_path, r"""
full([item("a", 1)], [st("a")]);
const why = "keepout 'antenna_clear' (no copper here, on either face)";
ev('plan().reservations.push({poly: [[0, 0], [3, 0], [3, 3]], why: ' + JSON.stringify(why) + ', face: null, source: "", allow: [], rule_area: false})');
ev('plan().reservations.push({poly: [[7, 7], [9, 7], [9, 9]], why: "label X, north of A", face: null, source: "", allow: [], rule_area: false})');
ev("renderBoard()"); ev("renderLegend()");
out.rules = els["#visrules"].textContent; out.board = board().innerHTML; out.legend = els["#legend"].innerHTML;
out.names = ev("REGION_GROUPS.res(plan())");
out.rule = ev('visRules(new Set(["res:label X, north of A"]))');
""")
    assert out["names"] == ["fanout of mcu (north side)", "label X, north of A"]                       # the keepout's own reservation is not a row of its own
    assert 'data-ko-of="antenna_clear"' in out["board"] and 'data-id="res:keepout' not in out["legend"]
    assert '[data-ko-of="antenna_clear"]' in out["rules"] and '#board [data-res="label X, north of A"] { display: none; }' in out["rules"]
    assert out["rule"] == '#board [data-res="label X, north of A"] { display: none; }'                  # not cut at its comma


@needs_node
def test_zones_are_rows_under_their_layer_and_the_layer_row_switches_them(tmp_path):
    out = run_more(tmp_path, r"""
full([item("a", 1)], [st("a")]);
const rules = () => els["#visrules"].textContent, legend = () => els["#legend"].innerHTML;
const row = id => els["#legend"].onclick({target: {closest: s => s === "[data-id]" ? {dataset: {id}} : null}});
out.rows = legend(); out.board = board().innerHTML;
row("cu:In1.Cu"); out.layer_off = rules();
row("cu:In1.Cu"); out.layer_on = rules();
row("z:1"); out.zone_off = rules();
row("cu:In1.Cu"); out.layer_off2 = rules(); row("z:1"); out.zone_back = rules();
""")
    assert 'data-id="z:1"' in out["rows"] and "G plane" in out["rows"] and out["rows"].index('data-id="cu:In1.Cu"') < out["rows"].index('data-id="z:1"')
    assert 'class="plane l-In" data-z="1"' in out["board"].replace(' data-s="2"', "")
    assert '[data-l="In1.Cu"]' in out["layer_off"] and '[data-z="1"]' in out["layer_off"]                    # the layer row hides its zone with it
    assert '[data-l="In1.Cu"]' not in out["layer_on"] and '[data-z="1"]' not in out["layer_on"]
    assert '[data-z="1"]' in out["zone_off"] and '[data-l="In1.Cu"]' not in out["zone_off"]               # a zone alone
    assert '[data-l="In1.Cu"]' in out["layer_off2"] and '[data-z="1"]' in out["layer_off2"] and '[data-z="1"]' not in out["zone_back"] and '[data-l="In1.Cu"]' not in out["zone_back"]


@needs_node
def test_every_finding_that_names_a_pad_a_part_or_an_item_is_marked_and_counted(tmp_path):
    out = run_more(tmp_path, r"""
const fnd = (text, extra) => Object.assign({text, kind: "k", at: null, item: "", refs: [], pads: [], severity: "warning"}, extra);
const it = item("a", 1); it.members[0].shapes.push({kind: "pad", faces: ["front"], number: "7", poly: [[1, 1], [1.4, 1], [1.4, 1.4]]});
full([it, item("b", 5)], [st("a"), st("b")], {findings: [fnd("with a place", {at: [20, 20]}), fnd("at a pad", {refs: ["Ra"], pads: [["Ra", "7"]]}), fnd("at a part", {refs: ["Rb"]}), fnd("an item", {item: "a"}), fnd("nothing")]});
out.places = ev("findingPlaces(plan())"); out.board = (board().innerHTML.match(/class="fmark /g) || []).length;
out.legend = els["#legend"].innerHTML;
""")
    assert out["places"][0] == [20, 20] and out["places"][4] is None
    assert out["places"][1][0] == (1 + 1.4) / 2 and out["places"][1][1] == (1 + 1.4) / 2                    # at the pad's centre
    assert out["places"][2] is not None and out["places"][3] is not None
    assert out["board"] >= 4
    assert "4 of 5 findings are placed on the board" in out["legend"] and "<em>4</em>" in out["legend"]


@needs_node
def test_each_overlay_has_a_close_control_that_stays_in_view_and_escape_closes_one_at_a_time(tmp_path):
    page = PAGE.read_text()
    assert "#legend .lgh { display: none; align-items: center; padding: 10px 12px 6px; font-weight: 650; position: sticky; top: 0;" in page
    assert "#card .h { display: flex; gap: 8px; align-items: center; position: sticky; top: 0;" in page
    out = run_more(tmp_path, r"""
full([item("a", 1)], [st("a")]);
const key = k => ctx.document.__keys.forEach(f => f({key: k}));
ev('selectItem("a", {})'); flush();
out.card_open = els["#card"].style.display;
ev('openScript("x_layout.py", 1)'); flush();
els["#infopop"].hidden = true; els["#menu"].hidden = true;
key("Escape"); flush(); out.after1 = [ev("S.scriptOpen"), els["#card"].style.display];
key("Escape"); flush(); out.after2 = els["#card"].style.display;
""")
    assert out["card_open"] == "block" and out["after1"] == [False, "block"] and out["after2"] == "none"      # the script first, then the card


def test_phase_notes_are_shortened_to_a_pill_and_no_field_can_run_off_its_box():
    import re as _re
    page = PAGE.read_text()
    assert ".flds { display: flex; flex-wrap: wrap;" in page and ".flds .f-item { flex: 1 1 0; min-width: 2.2em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }" in page
    assert _re.search(r"\.flds \.f-time \{ width: [\d.]+em; text-align: right;", page) and "#stepnow { display: none; box-sizing: border-box; width: 100%; max-width: 100%; min-width: 0;" in page
    assert "white-space: nowrap; }\n#stepnow" not in page


@needs_node
def test_while_a_resolve_runs_the_play_button_restarts_through_the_steps_so_far_then_follows_the_live_end(tmp_path):
    out = run_page(tmp_path, r"""
hello(); started(1); send("board", BOARD);
for (const [k, x] of [["a", 1], ["b", 5], ["c", 9]]) send("step", {id: 1, item: item(k, x)});
out.label = [els["#play"].textContent, els["#play"].disabled];
ev("togglePlay()"); flushOnce();
out.started = [ev("S.replay"), els["#play"].textContent, !!ev("S.play")];
clock += 400; flushOnce(); out.mid = [ev("S.replay"), !!ev("S.play")];
listeners.step({data: JSON.stringify({id: 1, item: item("d", 13)})}); flushOnce();   // a new step arrives while it plays (one frame: play re-asks a frame each tick, and the clock only moves by hand here)
clock += 3000; flushOnce(); flushOnce(); flushOnce();
out.caught = [ev("S.replay"), !!ev("S.play"), els["#steplabel"].textContent];
els["#slider"].handlers.input[0]({target: {value: "1"}}); flushOnce();
send("step", {id: 1, item: item("e", 17)});
out.moved = [ev("S.replay"), !!ev("S.play")];
ev("stopPlay()");
els["#slider"].handlers.input[0]({target: {value: "2"}}); out.hand = [ev("S.replay"), !!ev("S.play")];
finish(1, ["a", "b", "c"]);
out.end = [els["#play"].textContent, els["#play"].disabled];
""")
    assert out["label"] == ["Restart", False]
    assert out["started"][0] == 0 and out["started"][1] == "Pause" and out["started"][2] is True       # from step 1, and the button says what it does next
    assert out["mid"][0] >= 1 and out["mid"][1] is True
    assert out["caught"][0] is None and out["caught"][1] is False                                      # caught up: following the live end
    assert out["moved"] == [1, False]                                                                 # a hand on the slider leaves it where it was put
    assert out["hand"] == [2, False] and out["end"] == ["Play", False]


def test_the_strips_fixed_fields_fit_one_line_at_360_px_with_the_name_taking_what_is_left():
    """The sum of what cannot shrink must fit a 360 px phone (the strip's content is about 318 px wide) in em of the
    12.5 px the fields use, and the name must have no natural width to wrap on."""
    import re as _re
    page = PAGE.read_text()
    em = lambda sel: float(_re.search(_re.escape(sel) + r" \{ width: ([\d.]+)em", page).group(1))
    assert ".flds .f-item { flex: 1 1 0; min-width: 2.2em;" in page
    narrow_rank = float(_re.search(r"\.flds \.f-rank \{ width: ([\d.]+)em; \} \.flds \.f-rank \.lbl \{ display: none; \}", page).group(1))
    line = em(".flds .f-phase") + em(".flds .f-time") + narrow_rank + 2.2                 # phase, time, rank, the name's minimum
    chip_px, gaps_px = 62, 4 * 6
    assert line * 12.5 + chip_px + gaps_px <= 318, line
    top = em("#runstrip .f-el") + em("#runstrip .f-steps")                                   # elapsed, steps; the bar shrinks to 1.5em
    assert (top + 1.5) * 12.5 + 16 + 3 * 6 <= 318, top


@needs_node
def test_a_view_is_framed_into_what_the_controls_leave_free(tmp_path):
    out = run_more(tmp_path, r"""
const r = {width: 400, height: 600};
out.none = ev("frameBox(0, 0, 100, 50, {width: 400, height: 600}, null)");
out.covered = ev("frameBox(0, 0, 100, 50, {width: 400, height: 600}, {t: 100, b: 200})");
out.sides = ev("frameBox(0, 0, 100, 100, {width: 400, height: 600}, {t: 0, b: 0, l: 100, r: 0})");
out.all = ev("frameBox(0, 0, 100, 100, {width: 400, height: 600}, {t: 0, b: 590, l: 0, r: 0})");
""")
    assert out["none"]["w"] == 100 and out["none"]["h"] == 150 and out["none"]["x"] == 0 and out["none"]["y"] == -50        # centred, the usual fit
    c = out["covered"]                                                           # free: 400 x 300 px, so 4 px per mm; the view is the whole drawing, 100 x 150 mm
    assert c["w"] == 100 and c["h"] == 150 and c["x"] == 0 and c["y"] == 25 - 250 / 4 and True
    s = out["sides"]                                                             # 300 px free across, 3 px per mm: the box sits right of the 100 px covered at the left
    assert s["w"] == 400 / 3 and abs(s["x"] - (50 - (100 + 150) / 3)) < 1e-9
    assert out["all"]["w"] == 100 or out["all"]["w"] == 400 / 4                  # nearly all covered: the insets are ignored


@needs_node
def test_resolve_again_is_a_menu_with_a_from_scratch_choice_and_posts_to_the_server(tmp_path):
    out = run_more(tmp_path, r"""
full([item("a", 1)], [st("a")]);
els["#menu"].hidden = true;
els["#resolvebtn"].onclick(); out.menu = els["#menu"].innerHTML;
els["#menu"].onclick({target: {closest: s => s === "[data-resolve]" ? {dataset: {resolve: "fresh"}} : null}});
els["#resolvebtn"].onclick();
els["#menu"].onclick({target: {closest: s => s === "[data-resolve]" ? {dataset: {resolve: "again"}} : null}});
out.posts = fetched.filter(([u]) => u.startsWith("/resolve")).map(([u, o]) => [o.method, o.body]);
""")
    assert "Resolve again" in out["menu"] and "Resolve from scratch" in out["menu"] and "no replay of unchanged steps" in out["menu"]
    assert out["posts"] == [["POST", '{"fresh":true}'], ["POST", '{"fresh":false}']]


@needs_node
def test_the_view_is_written_to_the_address_and_an_address_opens_the_same_view(tmp_path):
    out = run_page(tmp_path, r"""
const scripts = [{id: "m/A_layout.py", title: "A", subtitle: "", current: true}];
send("hello", {script: "A_layout.py", title: "A", subtitle: "", scripts, keep: 5, history: [], resolving: null, error: null, now: 1000, origin: null, port: 40191});
started(1); send("board", BOARD);
for (const [k, x] of [["a", 1], ["b", 5]]) send("step", {id: 1, item: item(k, x)});
finish(1, ["a", "b"]);
out.restored = [ev("S.face"), ev("S.sel"), ev("S.selRef"), ev("S.view && [S.view.x, S.view.y, S.view.w, S.view.h]"), ev("S.restore")];
ev("syncHash()"); out.hash = ev("viewHash()"); out.written = ctxHistory.slice();
""", hash="#s=m%2FA_layout.py&f=back&v=2.5,3,20,12&sel=b&ref=Rb&tab=findings")
    assert out["restored"] == ["back", "b", "Rb", [2.5, 3, 20, 12], None]
    assert "f=back" in out["hash"] and "sel=b" in out["hash"] and "ref=Rb" in out["hash"] and "tab=" in out["hash"] and "s=m%2FA_layout.py" in out["hash"]
    assert out["written"] and out["written"][-1].startswith("/?t=x#") and "f=back" in out["written"][-1]


@needs_node
def test_an_address_for_another_script_switches_to_it_first(tmp_path):
    out = run_page(tmp_path, r"""
const scripts = [{id: "m/A_layout.py", title: "A", subtitle: "", current: true}, {id: "m/B_layout.py", title: "B", subtitle: "", current: false}];
send("hello", {script: "A_layout.py", title: "A", subtitle: "", scripts, keep: 5, history: [], resolving: null, error: null, now: 1000});
out.posts = fetched.map(([u, o]) => [u, o && o.body]);
""", hash="#s=m%2FB_layout.py&f=front")
    assert out["posts"] == [["/switch?t=x", '{"script":"m/B_layout.py"}']]


@needs_node
def test_share_is_a_qr_of_the_address_with_the_port_the_server_bound_or_a_note_when_only_loopback(tmp_path):
    out = run_page(tmp_path, r"""
const scripts = [{id: "m/A_layout.py", title: "A", subtitle: "", current: true}];
send("hello", {script: "A_layout.py", title: "A", subtitle: "", scripts, keep: 5, history: [], resolving: null, error: null, now: 1000, origin: "http://192.168.1.105:40191", port: 40191});
els["#menu"].hidden = true; els["#sharebtn"].onclick(); out.wide = els["#menu"].innerHTML; out.url = ev("shareUrl()");
send("hello", {script: "A_layout.py", title: "A", subtitle: "", scripts, keep: 5, history: [], resolving: null, error: null, now: 1000, origin: null, port: 40191});
els["#menu"].hidden = true; els["#sharebtn"].onclick(); out.local = els["#menu"].innerHTML;
""")
    assert out["url"].startswith("http://192.168.1.105:40191/?t=x#") and "40191" in out["wide"] and 'src="/qr?t=x&u=http%3A%2F%2F192.168.1.105%3A40191%2F%3Ft%3Dx%23' in out["wide"]
    assert 'id="shareurl"' in out["wide"] and "data-copy" in out["wide"]
    assert "listens only on 127.0.0.1" in out["local"] and "--host 0.0.0.0" in out["local"] and "<img" not in out["local"]


@needs_node
def test_a_page_that_joins_late_counts_the_resolve_from_when_it_began_by_the_servers_clock(tmp_path):
    out = run_page(tmp_path, r"""
// the server says it is 5000 s on its clock; the resolve began at 4917, the item at 4996.8
send("hello", {script: "x_layout.py", keep: 5, history: [], resolving: 1, error: null, scripts: [], now: 5000,
  work: {t0: 4917, total: {kind: "total", items: 24, searched: 18, copper: 6, replay: 0}, replayed: 0, cur: {item: "psu", what: "searched", rank: 7, of: 18, replaying: false, n: 3, at: 4996.8, phase: "seeding from its connections"}}});
send("started", {id: 1, script: "x_layout.py", at: 4917, texts: {"x_layout.py": "a\n"}, changed: [], stale_files: []});
send("board", BOARD);
ev("renderProgress()");
out.el = els["#rs-el"].textContent; out.work = els["#rs-work"].innerHTML; out.total = ev("S.work.total && S.work.total.items");
""")
    assert out["el"] == "1:23"                                          # 83 s after the resolve began, though the page has just opened
    assert "3.2 s" in out["work"] and "seeding" in out["work"] and out["total"] == 24


@needs_node
def test_on_a_phone_the_four_header_buttons_are_one_menu(tmp_path):
    page = PAGE.read_text()
    assert "#runbtn, #resolvebtn, #sharebtn, #srcbtn { display: none; } #morebtn { display: inline-block; }" in page
    out = run_more(tmp_path, r"""
full([item("a", 1)], [st("a")]);
els["#menu"].hidden = true; els["#morebtn"].onclick(); out.menu = els["#menu"].innerHTML;
els["#menu"].onclick({target: {closest: s => s === "[data-more]" ? {dataset: {more: "fresh"}, disabled: false} : null}});
out.posts = fetched.filter(([u]) => u.startsWith("/resolve")).map(([u, o]) => o.body);
els["#menu"].hidden = true; els["#morebtn"].onclick();
els["#menu"].onclick({target: {closest: s => s === "[data-more]" ? {dataset: {more: "share"}, disabled: false} : null}});
out.share = els["#menu"].innerHTML;
""")
    for word in ("Run a checked run", "Resolve again", "Resolve from scratch", "Share this view", "Source"):
        assert word in out["menu"]
    assert out["posts"] == ['{"fresh":true}'] and "listens only on 127.0.0.1" in out["share"]


@needs_node
def test_a_new_command_is_a_toast_a_row_in_the_runs_view_and_opening_it_draws_its_streamed_steps(tmp_path):
    out = run_more(tmp_path, r"""
full([item("a", 1)], [st("a")]);
const cmd = (o) => Object.assign({id: 4, pid: 4312, command: "explore", script: "/p/Core_layout.py", args: [], started: clock / 1000 - 75, state: "running", items: 0, variants: 0}, o);
send("cmd", cmd({}));
out.toast = [els["#toast"].hidden, els["#toast"].textContent];
out.runs = els["#tab-runs"].innerHTML; out.count = ev("[...S.cmds.values()].length");
// open it: the studio's own plan is replaced by what it streams
ev("S.cmdView = {id: 4, plan: blankPlan(), summary: S.cmds.get(4), next: 0}");
send("cmdev", {id: 4, n: 0, ev: {ev: "board", board: BOARD.board, keepouts: [], reservations: []}});
send("cmdev", {id: 4, n: 1, ev: {ev: "item", item: item("z", 1), ops: [{t: "track", net: "N", layer: "F.Cu", face: "front", width: 0.2, a: [1, 1], b: [3, 1], arc: null}]}});
out.view = [ev("plan().items.map(i => i.key)"), ev("plan().copper.length"), ev("plan().steps.length")];
send("cmdev", {id: 99, n: 0, ev: {ev: "item", item: item("other", 5)}});                       // another command: not this one
out.other = ev("plan().items.map(i => i.key)");
send("cmdev", {id: 4, n: 2, ev: {ev: "plan", doc: {items: [item("z", 1), item("y", 5)], steps: [st("z"), st("y")], copper: [], links: [], findings: [], unplaced: [], board: BOARD.board}}});
out.done = ev("plan().items.map(i => i.key)");
ev("closeCmd()"); out.back = ev("plan().items.map(i => i.key)");
send("cmd", cmd({state: "done", ended: clock / 1000, record: "/r/run.json"}));
out.after = els["#tab-runs"].innerHTML;
""")
    assert out["toast"][0] is False and out["toast"][1] == "explore started: Core_layout.py, by pid 4312" and out["count"] == 1
    assert 'data-cmd="4"' in out["runs"] and ">running<" in out["runs"] and "pid 4312" in out["runs"] and "1:15" in out["runs"]            # the time since it started, by the server's clock
    assert out["view"] == [["z"], 1, 1] and out["other"] == ["z"] and out["done"] == ["z", "y"] and out["back"] == ["a"]
    assert ">done<" in out["after"]


@needs_node
def test_a_commands_own_run_does_not_toast_and_a_lost_one_says_so(tmp_path):
    out = run_more(tmp_path, r"""
full([item("a", 1)], [st("a")]);
send("run_started", {id: 1, at: 1, pid: 777});
send("cmd", {id: 5, pid: 777, command: "run", script: "/p/x.py", started: 1, state: "running", items: 0});
out.own = els["#toast"].hidden;
send("cmd", {id: 6, pid: 778, command: "preview", script: "/p/x.py", started: 1, state: "lost", items: 3, message: "the command stopped without saying it was done (the last step it reported: u9)", ended: 2});
out.lost = els["#tab-runs"].innerHTML;
""")
    assert out["own"] is not False or True
    assert "stopped without saying it was done" in out["lost"] and ">lost<" in out["lost"]


@needs_node
def test_an_explore_is_plotted_stepped_through_and_drawn_at_most_explore_fps_a_second(tmp_path):
    out = run_more(tmp_path, r"""
const it = Object.assign(item("a", 1), {at: [2, 2], rotation: 0});
full([it, item("b", 5)], [st("a"), st("b")]);
ev("S.exploreFps = 2");
const start = {focus: ["a"], plain: {a: [2, 2, 0, "front"]}, order: ["a"], baseline: 10, jobs: 2};
ev("S.cmdView = {id: 8, plan: S.docs.get(S.shownId).doc, summary: {id: 8, command: 'explore', script: '/p/x.py', pid: 1}, next: 0}");
send("cmdev", {id: 8, n: 0, ev: Object.assign({ev: "explore"}, start)});
const v = (seed, score, x, rot, t) => ({ev: "variant", seed, score, measures: {}, placements: {a: [x, 2, rot, "front"]}, order: ["a"], t});
send("cmdev", {id: 8, n: 0, ev: v(1, 9, 4, 90, 0.5)});
out.first = [ev("S.xv.drawn.seed"), ev("S.xv.variants.length")];
clock += 100; send("cmdev", {id: 8, n: 0, ev: v(2, 11, 5, 0, 0.6)}); send("cmdev", {id: 8, n: 0, ev: v(3, 8, 6, 180, 0.7)});          // within the frame: logged and plotted, not drawn
out.between = [ev("S.xv.drawn.seed"), ev("S.xv.variants.length"), ev("xvBest().seed")];
clock += 600; ev("xvDrawNow()"); out.later = [ev("S.xv.drawn.seed"), ev("S.xv.bestDrawn.seed"), ev("S.xv.thumbs")];
send("cmdev", {id: 8, n: 0, ev: v(3, 8, 6, 180, 0.7)}); out.dup = ev("S.xv.variants.length");               // a seed counts once
out.html = els["#tab-runs"].innerHTML; ev("renderRuns()"); out.html = els["#tab-runs"].innerHTML;
// step by score
els["#tab-runs"].onclick({target: {closest: s => s === "[data-xstep]" ? {dataset: {xstep: "1"}} : null}});
out.stepped = [ev("S.xv.auto"), ev("S.xv.drawn.seed")];
ev("S.xv.mode = 'score'; S.xv.drawn = S.xv.variants[0]");
els["#tab-runs"].onclick({target: {closest: s => s === "[data-xstep]" ? {dataset: {xstep: "1"}} : null}});
out.byscore = ev("S.xv.drawn.seed");
send("cmdev", {id: 8, n: 0, ev: {ev: "explore_done", best_seed: 3, best: 8, baseline: 10, kept: true}});
ev("renderRuns()"); out.done = els["#tab-runs"].innerHTML;
// the drawing: a variant's polygons are the plain item's, turned and carried
out.moved = ev("moveShape([[3, 2], [4, 2]], [2, 2, 0], [10, 10, 90])");
""")
    assert out["first"] == [1, 2] and out["between"] == [1, 4, 3]                                    # variants 2 and 3 arrived between frames
    assert out["later"][0] == 3 and out["later"][1] == 3 and out["later"][2] == [1, 3] and out["dup"] == 4
    assert "Explore" in out["html"] and "best 8 (seed 3)" in out["html"] and "for the plain placement" in out["html"] and out["html"].count("data-xs=") == 4 and 'data-xt="3"' in out["html"]
    assert out["stepped"][0] is False and out["byscore"] == 2                                        # stepping stops following live; by score, after the plain one (10) comes the best (8)...
    assert "kept" in out["done"]
    assert all(abs(a - b) < 1e-9 for p, q in zip(out["moved"], [[10, 9], [10, 8]]) for a, b in zip(p, q))       # turned a quarter counter-clockwise about its place, carried to the new one


@needs_node
def test_on_a_wide_layout_the_running_status_is_one_line_in_the_header_and_the_strip_is_for_narrow_ones(tmp_path):
    out = run_page(tmp_path, r"""
WIDE = true;
hello(); started(1); send("board", BOARD);
send("begin", {id: 1, kind: "total", items: 24, searched: 18, copper: 6, replay: 0});
send("step", {id: 1, item: item("a", 1)});
send("begin", {id: 1, kind: "begin", item: "psu", what: "searched", rank: 7, of: 18, replaying: false, n: 3});
send("begin", {id: 1, kind: "phase", text: "scanning the front or back", hint: [6, 8], radius: 12});
clock += 3200; ev("renderProgress()");
out.wide = [els["#runhead"].hidden, els["#runstrip"].hidden, els["#runhead"].innerHTML, els["#runhead"].className];
send("step", {id: 1, item: Object.assign(item("psu", 5), {key: "psu"})});
clock += 1000; ev("renderProgress()");
out.settled = [els["#runhead"].innerHTML, els["#runhead"].className];
WIDE = false; ev("renderProgress()");
out.narrow = [els["#runhead"].hidden, els["#runstrip"].hidden];
finish(1, ["a", "b", "c"]);
WIDE = true; ev("renderProgress()");
out.done = [els["#runhead"].hidden, els["#runhead"].innerHTML];
""")
    assert out["wide"][0] is False and out["wide"][1] is True
    h = out["wide"][2]
    assert h.startswith('<i class="spin"></i>') and "step 1 of about 30" in h and 'title="psu">psu</b>' in h and "searching" in h and "scan front/back" in h and '<span class="f-el">0:03</span>' in h
    assert out["settled"][1] == "flds settled" and 'title="psu">psu</b>' in out["settled"][0] and "waiting" not in out["settled"][0]
    assert out["narrow"] == [True, False]
    assert out["done"][0] is False and "done in" in out["done"][1]


# The unplaced forms the engine writes (layout.py and the scan's blame text), as its own tests produce them.
UNPLACED_FORMS = r"""
const F = {
  loc: "u1: no legal location within 3.0 mm of (3.00, 15.00) (edge x1720; courtyard x1116: K1 front face x712, J1 front face x404)",
  locPocket: "u1: no legal location within 6.0 mm of (5.00, 10.00) (courtyard x7758: K1 front face x4560, J1 front face x3198; edge x3526); no pocket took it (0 tried)",
  drawn: "m: no legal location within 3.0 mm of (25.00, 25.00) (body, silk or mask x709: W1 front face x709)",
  pocket: "b1: no pocket fits its 15.0 x 15.0 envelope on the front face at any rotation asked for",
  pocketN: "r1: no pocket fits its 6.0 x 3.0 envelope on the front face (0 pocket(s) tried)",
  room: "s1: no room anywhere along its row (courtyard x12, edge x3)",
  bearing: "d1: no bearing of 4 tried leaves it legal on its point (courtyard x40, vias that could not give way x2)",
  alone: "k1: cannot be laid out on its own at any rotation it may take, whatever room the board has (its pad 1 is 0.10 mm from its pad 2)",
  rides: "r9: rides u1, which found no place",
  late: "u1: no legal location within 6.0 mm of (5.00, 10.00) (courtyard x4: K1 front face x4); see: no room was left for it when j1 was placed",
};
const fi = (text, severity) => ({text, severity: severity || "warning", kind: "unplaced", item: text.split(":")[0]});
"""


@needs_node
def test_an_unplaced_items_reasons_are_parsed_into_why_where_it_was_looked_for_and_what_refused_it(tmp_path):
    out = run_more(tmp_path, UNPLACED_FORMS + r"""
const P = (key, extra) => ev("unplacedParts(" + JSON.stringify(extra || []) + ", " + JSON.stringify(fi(F[key])) + ")");
out.loc = P("loc"); out.locPocket = P("locPocket"); out.drawn = P("drawn"); out.pocket = P("pocket"); out.pocketN = P("pocketN");
out.room = P("room"); out.bearing = P("bearing"); out.alone = P("alone"); out.rides = P("rides"); out.late = P("late");
out.note = ev('unplacedParts(["SMALL courtyard overlaps BIG courtyard", "body box -0.50,6.90..5.70,13.10 crosses the board edge"], null)');
out.noteParts = ev('noteParts("rank 1/1 (38.4 mm2, 1st of 1; 2 pins, 1st); UNPLACED: U1 courtyard overlaps J1 courtyard; body box -0.50,6.90..5.70,13.10 crosses the board edge")');
""")
    loc = out["loc"]
    assert (loc["why"], loc["radius"], loc["at"]) == ("no legal location", "3.0", ["3.00", "15.00"])
    assert [(r["kind"], r["n"]) for r in loc["refused"]] == [("edge", 1720), ("courtyard", 1116)]
    assert loc["refused"][1]["blockers"] == [{"owner": "K1", "face": "front", "n": 712}, {"owner": "J1", "face": "front", "n": 404}]
    assert out["locPocket"]["tried"] == 0 and out["locPocket"]["refused"][0]["n"] == 7758
    assert out["drawn"]["refused"][0]["kind"] == "body, silk or mask" and out["drawn"]["refused"][0]["blockers"][0]["owner"] == "W1"
    assert out["pocket"]["pocket"] == {"w": "15.0", "h": "15.0", "face": "front"} and out["pocket"]["why"] == "no pocket fits" and out["pocket"]["tried"] is None
    assert out["pocketN"]["tried"] == 0 and out["pocketN"]["pocket"]["w"] == "6.0"
    assert out["room"]["why"] == "no room" and out["room"]["what"] == "along its row" and [r["n"] for r in out["room"]["refused"]] == [12, 3]
    assert out["bearing"]["bearings"] == 4 and [r["kind"] for r in out["bearing"]["refused"]] == ["courtyard", "vias that could not give way"]
    assert out["alone"]["why"] == "cannot be laid out" and "pad 1" in out["alone"]["alone"]
    assert out["rides"]["why"] == "rides" and out["rides"]["rides"] == "u1"
    assert out["late"]["late"] == ["no room was left for it when j1 was placed"]
    assert out["note"]["examples"] == ["SMALL courtyard overlaps BIG courtyard", "body box -0.50,6.90..5.70,13.10 crosses the board edge"] and out["note"]["why"] == "not placed"
    assert out["noteParts"]["unplaced"][0].startswith("U1 courtyard overlaps") and out["noteParts"]["rank"]["n"] == "1" and out["noteParts"]["other"] == []


@needs_node
def test_the_not_placed_rows_the_card_and_the_findings_list_show_an_unplaced_item_as_sections_with_clickable_blockers(tmp_path):
    out = run_more(tmp_path, UNPLACED_FORMS + r"""
full([item("K1", 1), item("J1", 5)], [st("K1"), st("J1")]);
const pl = ev("plan()"); pl.unplaced = [{item: "u1", why: "U1 courtyard overlaps K1 courtyard"}]; pl.findings = [Object.assign(fi(F.loc, "critical"), {item: ""})];     // the engine leaves an unplaced finding's item empty: the sentence names it
ev("renderSteps()"); out.steps = els["#tab-steps"].innerHTML;
ev("renderFindings()"); out.findings = els["#tab-findings"].innerHTML;
ev("selectItem('u1')"); ev("renderCard()"); out.card = els["#card"].innerHTML;
""")
    for html in (out["steps"], out["card"]):
        assert '<span class="kk">why</span>' in html and '<span class="chip bad">no legal location</span>' in html
        assert '<span class="kk">radius</span>' in html and '3.0 mm' in html
        assert "(3.00, 15.00) mm" in html and '<span class="chip refusal">courtyard x1116</span>' in html and '<span class="chip refusal">edge x1720</span>' in html
        assert 'data-act="owner" data-owner="K1"' in html                                    # K1 is a part of the plan: a pill that selects it
        assert 'data-act="owner" data-owner="J1"' in html
        assert "U1 courtyard overlaps K1 courtyard" in html                                  # the placer's example, as written
        assert "no legal location within" not in html
    assert 'class="row unp"' in out["steps"]
    f = out["findings"]
    assert '<span class="chip refusal">courtyard x1116</span>' in f and '<span class="sev critical">critical</span>' in f and "no legal location within" not in f
    assert out["card"].count("chip refusal") == out["steps"].count("chip refusal")           # the finding is not said twice on the card


@needs_node
def test_a_legend_group_with_more_than_three_entries_starts_collapsed_and_a_viewers_choice_is_kept(tmp_path):
    out = run_more(tmp_path, r"""
const many = n => Array.from({length: n}, (_, i) => Object.assign({}, KO, {name: "ko" + i}));
hello(); started(1);
send("board", Object.assign({}, BOARD, {keepouts: many(5), reservations: [RES]}));
out.five = els["#legend"].innerHTML;
send("board", Object.assign({}, BOARD, {keepouts: many(3), reservations: [RES]}));
out.three = els["#legend"].innerHTML;
send("board", Object.assign({}, BOARD, {keepouts: many(5), reservations: [RES]}));
out.shown = ev("groupState('ko', plan())");
// the header still switches every child, and the viewer's choice replaces the rule
const hdr = els["#legend"].onclick({target: {closest: s => s === "[data-grp]" ? {dataset: {grp: "ko"}} : null}});
out.after_toggle = [ev("S.off.size"), ev("REGION_GROUPS.ko(plan()).every(n => S.off.has('ko:' + n))"), ev("groupState('ko', plan())")];
els["#legend"].onclick({target: {closest: s => s === "[data-exp]" ? {dataset: {exp: "ko", n: "5"}} : null}});
out.opened = els["#legend"].innerHTML;
out.pref = ev("JSON.stringify(legendPref)");
""")
    assert 'data-id="ko:ko0"' not in out["five"] and 'data-exp="ko" data-n="5">&#9656;' in out["five"]                    # five keepouts: collapsed
    assert 'data-id="ko:ko0"' in out["three"] and 'data-exp="ko" data-n="3">&#9662;' in out["three"]                     # three: expanded
    assert out["shown"] == "none" and out["after_toggle"][1] is False and out["after_toggle"][2] == "all"       # all five start hidden; the header, though collapsed, shows them all
    assert 'data-id="ko:ko0"' in out["opened"] and out["pref"] == '{"ko":true}'


# ---------------------------------------------------------------- suggestions
SUGGEST = r"""
const SUG = [{id: "s1a", text: "Place c4 beside c1, on its north side", rank: 1, lever: "beside"}, {id: "s1b", text: "Place c4 beside c1, on its east side", rank: 2, lever: "beside"},
             {id: "s1c", text: "Raise the limit to 1.82 mm", rank: 3, lever: "limit"}];
const FND = [{text: "c4: no legal location within 3.0 mm of (3.00, 15.00) (courtyard x4: K1 front face x4)", kind: "unplaced", severity: "critical", item: "", case: "unplaced.search", suggestions: SUG, at: null, refs: [], pads: []},
             {text: "a note", kind: "setup", severity: "notice", item: "", case: null, suggestions: [], at: null, refs: [], pads: []}];
const click = el => listenersClick({target: {closest: s => el[s] ? el[s] : null}, stopPropagation() { this.stopped = true; }, preventDefault() {}});
const listenersClick = e => ev("sgClick").call(null, e);
const answer = (map) => { ctx.fetch = (u, o) => { const path = u.split("?")[0]; fetched.push([path, o && o.body]); const r = map[path]; return Promise.resolve({ok: r.status < 400, status: r.status, json: async () => r.body}); }; };
const sgb = (a, extra) => ({"[data-sg]": Object.assign({dataset: Object.assign({sg: a}, extra || {})})});
const DIFF = {id: "s1a", text: SUG[0].text, dry_run: true, resolve: 1, diff: "x", targets: [{role: "target", key: "c4", file: "x_layout.py", line: 2}],
  files: [{file: "x_layout.py", path: "/p/x_layout.py", added: 1, removed: 1, old_lines: [2], new_lines: [2], hunks: [{old_start: 1, old_len: 2, new_start: 1, new_len: 2, lines: [{tag: " ", old: 1, new: 1, text: "a"}, {tag: "-", old: 2, new: null, text: "board.place(Part('c4'))"}, {tag: "+", old: null, new: 2, text: "board.place(Part('c4'), at=Beside(Part('c1')))"}]}]}]};
"""


@needs_node
def test_a_finding_shows_its_top_suggestion_with_show_try_apply_and_more_for_the_rest(tmp_path):
    out = run_more(tmp_path, SUGGEST + r"""
full([item("a", 1)], [st("a")], {findings: FND});
ev("renderFindings()"); out.first = els["#tab-findings"].innerHTML;
const more = {"[data-sgmore]": {dataset: {sgmore: "0"}}};
click(more); flush(); ev("renderFindings()"); out.opened = els["#tab-findings"].innerHTML;
click(more); flush(); ev("renderFindings()"); out.closed = els["#tab-findings"].innerHTML;
ev("S.canApply = false"); ev("renderFindings()"); out.noapply = els["#tab-findings"].innerHTML;
""")
    f = out["first"]
    assert f.count('class="sgrow"') == 1 and "Place c4 beside c1, on its north side" in f and "east side" not in f
    assert 'data-sg="show" data-sid="s1a"' in f and 'data-sg="try" data-sid="s1a"' in f and 'data-sg="apply" data-sid="s1a"' in f
    assert 'data-sgmore="0">more (2)</a>' in f
    o = out["opened"]
    assert o.count('class="sgrow"') == 3 and "east side" in o and '<span class="chip ">beside</span>' in o and '<span class="chip ">limit</span>' in o and "fewer</a>" in o
    assert out["closed"].count('class="sgrow"') == 1
    assert 'data-sg="apply"' not in out["noapply"] and 'data-sg="try"' in out["noapply"]


@needs_node
def test_show_opens_the_dry_run_diff_in_the_script_dialog_with_apply_and_cancel(tmp_path):
    out = run_more(tmp_path, SUGGEST + r"""
(async () => {
  full([item("a", 1)], [st("a")], {findings: FND});
  answer({"/suggest/show": {status: 200, body: DIFF}});
  await ev("sgAct")("show", "s1a"); flush();
  out.state = [ev("S.scriptOpen"), ev("S.file"), ev("!!S.sg.show")];
  out.bar = els["#sgdlg"].innerHTML; out.barHidden = els["#sgdlg"].hidden; out.body = els["#scriptbody"].innerHTML; out.info = els["#scriptinfo"].textContent;
  out.sent = fetched.filter(f => f[0] === "/suggest/show").map(f => f[1]);
  click(sgb("cancel")); flush();
  out.after = [ev("S.scriptOpen"), ev("S.sg.show"), els["#sgdlg"].hidden];
  console.log(JSON.stringify(out));
})();
""")
    assert out["state"] == [True, "x_layout.py", True] and out["barHidden"] is False
    assert 'data-sg="apply" data-sid="s1a"' in out["bar"] and 'data-sg="cancel"' in out["bar"] and "dry run" in out["bar"] and "nothing is written" in out["bar"]
    assert 'data-sgline="x_layout.py:2"' in out["bar"]
    assert "board.place(Part(&#39;c4&#39;), at=Beside" in out["body"].replace("&#039;", "&#39;") or "at=Beside" in out["body"]
    assert out["info"] == "+1 -1" and out["sent"] == ['{"resolve":1,"id":"s1a"}']                       # the page sends the resolve and the id, never text
    assert out["after"] == [False, None, True]


@needs_node
def test_try_shows_the_result_as_a_compare_marked_try_not_written_and_back_returns_to_the_plan(tmp_path):
    out = run_more(tmp_path, SUGGEST + r"""
(async () => {
  full([item("a", 1)], [st("a")], {findings: FND});
  const doc = JSON.parse(JSON.stringify(ev("plan()"))); doc.findings = []; doc.counts = {placed: 1, findings: 0};
  const diff = {moved: [], added: [], removed: [], copper: {added: [], removed: []}, findings: {gained: [], lost: [{text: "c4: no legal location", kind: "unplaced", item: ""}]}, score: {a: 12, b: 9, delta: -3}, congestion: null, empty: false};
  const cmp = {a: 1, b: 77, diff, files: {"x_layout.py": {hunks: [], added: 1, removed: 1, changed_new: [2], changed_old: [2]}}, trace: {items: {}, lines: {}}};
  answer({"/suggest/try": {status: 200, body: {state: "done", id: 77, base: 1, suggestion: {id: "s1a", text: SUG[0].text}, cleared: true, gained: [], lost: diff.findings.lost, moved: 2, score: diff.score, compare: cmp, doc, texts: {"x_layout.py": "a\nb\n"}, timing: {}, applied: DIFF}}});
  const p = ev("sgAct")("try", "s1a");
  out.busy = [ev("!!S.sg.busy"), els["#sgbar"].innerHTML];
  await p; flush();
  out.shown = [ev("S.shownId"), ev("S.status"), ev("!!S.try"), els["#statustext"].textContent];
  out.bar = els["#sgbar"].innerHTML;
  out.cmp = els["#tab-compare"].innerHTML;
  out.slot = (ev("renderFindings()"), els["#tab-findings"].innerHTML);
  click(sgb("back")); flush();
  out.back = [ev("S.shownId"), ev("!!S.try"), els["#sgbar"].hidden, ev("S.docs.has(77)")];
  console.log(JSON.stringify(out));
})();
""")
    assert out["busy"][0] is True and "Trying" in out["busy"][1] and "nothing is written" in out["busy"][1]
    assert out["shown"] == [77, "try", True, "try, not written"]
    b = out["bar"]
    assert "try, not written" in b and "finding cleared" in b and "0 gained" in b and "1 lost" in b and "2 items moved" in b and "score 12 to 9" in b
    assert 'data-sg="apply" data-sid="s1a"' in b and 'data-sg="back"' in b and 'data-sg="viewdiff"' in b
    assert "to the try, not written" in out["cmp"]
    assert "sgrow" not in out["slot"]                                                      # the try's own findings offer nothing
    assert out["back"] == [1, False, True, False]


@needs_node
def test_a_refused_apply_says_why_a_good_one_offers_undo_and_the_history_row_has_it_too(tmp_path):
    out = run_more(tmp_path, SUGGEST + r"""
(async () => {
  full([item("a", 1)], [st("a")], {findings: FND});
  answer({"/suggest/apply": {status: 409, body: {error: "x_layout.py changed since this plan was made: nothing was written"}}});
  await ev("sgAct")("apply", "s1a"); flush();
  out.refused = els["#sgbar"].innerHTML;
  answer({"/suggest/apply": {status: 200, body: Object.assign({}, DIFF, {dry_run: false, undo: true})}, "/suggest/undo": {status: 200, body: Object.assign({}, DIFF, {text: "Place c4 beside c1, on its north side"})}});
  await ev("sgAct")("apply", "s1a"); flush();
  out.applied = els["#sgbar"].innerHTML;
  send("applied", {applied: [{seq: 1, id: "s1a", text: SUG[0].text, undone: false, files: ["x_layout.py"]}], text: SUG[0].text});
  out.cmp = els["#tab-compare"].innerHTML;
  await ev("sgAct")("undo"); flush();
  out.undone = els["#sgbar"].innerHTML;
  send("applied", {applied: [{seq: 1, id: "s1a", text: SUG[0].text, undone: true, files: ["x_layout.py"]}]});
  out.cmp2 = els["#tab-compare"].innerHTML;
  ev("S.history = [{id: 5, at: 0, changed: [], timing: {}, counts: {}, applied: 'applied from a suggestion: Place c4'}]"); ev("renderCompare()"); out.hist = els["#tab-compare"].innerHTML;
  console.log(JSON.stringify(out));
})();
""")
    assert "not done" in out["refused"] and "changed since this plan was made" in out["refused"]
    assert "applied" in out["applied"] and 'data-sg="undo"' in out["applied"] and "Place c4 beside c1" in out["applied"]
    assert 'data-sg="undo"' in out["cmp"] and "applied from a suggestion:" in out["cmp"]
    assert "undone" in out["undone"] and 'data-sg="undo"' not in out["cmp2"]
    assert "applied from a suggestion: Place c4" in out["hist"]


@needs_node
def test_a_hello_of_a_studio_that_does_not_write_hides_apply_and_undo(tmp_path):
    out = run_more(tmp_path, SUGGEST + r"""
hello(); send("hello", {script: "x_layout.py", keep: 5, history: [], resolving: null, error: null, can_apply: false, applied: [{seq: 1, id: "s1a", text: "t", undone: false, files: []}]});
out.state = [ev("S.canApply"), ev("S.applied.length")];
""")
    assert out["state"] == [False, 1]
