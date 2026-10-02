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
const els = {};
let clock = 1000;
class FakeDate extends Date { static now() { return clock; } }
const fakeGroup = (key, s) => { const g = {dataset: {key, s: String(s)}, style: {}, cls: new Set(["item"])};
  g.classList = {toggle(c, on) { g.cls[on ? "add" : "delete"](c); }, add(c) { g.cls.add(c); }, remove(c) { g.cls.delete(c); }}; return g; };
const groups = html => [...html.matchAll(/<g class="item[^"]*" data-key="([^"]*)" data-s="(\d+)"/g)].map(m => fakeGroup(m[1], +m[2]));
const mk = sel => new Proxy({
  innerHTML: "", textContent: "", value: "", style: {}, dataset: {}, className: "", attrs: {}, max: 0, handlers: {}, disabled: false,
  classList: {toggle() {}, add() {}, remove() {}},
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
  document: {querySelector: stub, querySelectorAll: () => [], body: {dataset: {}}, elementFromPoint: () => null},
  window: {addEventListener() {}}, location: {search: "?t=x"}, matchMedia: () => ({matches: true}), Date: FakeDate,
  EventSource: class { constructor() { this.addEventListener = (n, f) => { listeners[n] = f; }; } },
  requestAnimationFrame: f => { frames.push(f); }, setInterval() {}, clearInterval() {}, setTimeout() {}, fetch: (u, o) => { fetched.push([u, o]); return Promise.reject(new Error("no")); },
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


def run_page(tmp_path, tail):
    """Run the page's script against the DOM stub, then `tail` (JavaScript that fills `out`); `out` as a dict."""
    text = PAGE.read_text()
    (tmp_path / "page.js").write_text(text[text.index("<script>") + 8:text.index("</script>")])
    (tmp_path / "run.js").write_text(PRELUDE + tail + "\nconsole.log(JSON.stringify(out));\n")
    done = subprocess.run(["node", str(tmp_path / "run.js"), str(tmp_path / "page.js")], capture_output=True, text=True)
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
out.steps = els["#steplist"].innerHTML;
out.files = els["#file"].innerHTML;
""")
    assert "<path" not in out["before_board"]
    assert "<path" in out["after_board"] and out["viewbox"]
    assert 'data-key="a"' in out["one"] and "<polygon" in out["one"] and 'data-key="b"' not in out["one"]
    assert out["two"].index('data-key="a"') < out["two"].index('data-key="b"')
    assert 'data-n="0"' in out["steps"] and 'data-n="1"' in out["steps"] and 'data-n="2"' not in out["steps"]
    assert "x_layout.py" in out["files"] and "placemat.toml" not in out["files"]


@needs_node
def test_the_slider_has_one_position_for_each_placement_step(tmp_path):
    """The positions are the steps that placed an item the board draws, in order: copper steps, a part that was not
    placed and a repeated step are not positions, and the count the page shows is the slider's maximum."""
    out = run_page(tmp_path, r"""
hello(); started(1); send("board", BOARD);
for (const [k, x] of [["a", 1], ["b", 5], ["c", 9]]) send("step", {id: 1, item: item(k, x)});
finish(1, ["a", "b", "c"]);
out.order = ev("placementSteps(plan())").map(s => s.item);
out.nsteps = ev("plan().steps.length");
out.max = els["#slider"].max;
out.label = els["#steplabel"].textContent;
out.at = [0, 1, 2, 3, 4].map(k => ev("itemsAtStep(plan(), " + k + ")"));
out.all = ev("itemsAtStep(plan(), null)");
out.other = ev("otherSteps(plan())").map(s => s.item);
out.tab = els["#tab-steps"].innerHTML;
""")
    assert out["nsteps"] == 8 and out["order"] == ["a", "b", "c"]
    assert out["max"] == 3 and out["label"] == "3 / 3"
    assert out["at"] == [[], ["a"], ["a", "b"], ["a", "b", "c"], ["a", "b", "c"]]     # steps 1..k, and no position past the last
    assert out["all"] == ["a", "b", "c"]
    assert out["other"] == ["fanout a", "escape U1", "escape U1", "a"]        # "gone" is listed as not placed
    assert out["tab"].count('data-n="') == 3


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
ev("setReplay(2)"); flush();
out.k2 = shown(); out.w2 = writes.splice(0);
ev("setReplay(1)"); flush();
out.back = shown(); out.w3 = writes.splice(0);
ev("setReplay(0)"); flush();
out.k0 = shown(); out.label0 = els["#steplabel"].textContent;
ev("setReplay(3)"); flush();
out.end = shown(); out.replay = ev("S.replay");
""")
    hidden = lambda state: [i for i, gs in enumerate(state) if gs and all(d == "none" for d in gs)]
    assert hidden(out["start"]) == []
    assert hidden(out["k1"]) == [1, 2] and set(out["w1"]) == {"b", "c"}       # at 1 only a shows
    assert hidden(out["k2"]) == [2] and out["w2"] == ["b"]                      # a step forward touches one item
    assert hidden(out["back"]) == [1, 2] and out["w3"] == ["b"]
    assert hidden(out["k0"]) == [0, 1, 2] and out["label0"] == "0 / 3"
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
out.order = ev("placementSteps(plan())").map(s => s.item);
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
click("via"); click("labels"); click("link:over"); click("cu:In1.Cu"); click("res:fanout of mcu (north side)");
out.rules = els["#visrules"].textContent;
els["#legend"].onclick({target: {closest: s => s === "[data-exp]" ? {dataset: {exp: "ko"}} : null}});
out.expanded = els["#legend"].innerHTML;
click("ko:antenna_clear");
out.ko = els["#visrules"].textContent;
out.rules2 = ev('visRules(new Set(["cy", "ko", "cu:F.Cu", "link:ok"]))');
""")
    assert out["start"] == "#board .ref { display: none; }"                      # designators are off until asked for
    for row in ('data-id="cy"', 'data-id="cu:F.Cu"', 'data-id="via"', 'data-id="link:ok"', 'data-id="link:over"', 'data-id="ko"', 'data-id="res"', 'data-id="findings"'):
        assert row in out["legend"]
    assert '<em>1</em>' in out["legend"] and "within its limit" in out["legend"]
    assert "#board .viag { display: none; }" in out["rules"] and ".ref" not in out["rules"]               # via off, designators on
    assert '#board .lkg[data-st="over"]' in out["rules"] and '#board [data-l="In1.Cu"]' in out["rules"] and '[data-res="fanout of mcu (north side)"]' in out["rules"]
    assert 'data-id="ko:antenna_clear"' in out["expanded"]                          # a keepout has its own row
    assert '[data-ko="antenna_clear"]' in out["ko"]
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
    assert "rotated 0\u00b0" in out["card"]
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
    assert "antenna_clear" in out["card"] and "F.Cu" in out["card"] and "tracks, vias" in out["card"] and "GND" in out["card"] and "no copper here" in out["card"]
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
    assert "C2" in out["part"] and "select its module" in out["part"] and "psu" in out["part"]
    assert "module psu" in out["module"] and 'data-ref="C1"' in out["module"] and 'data-ref="C2"' in out["module"]
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
    assert "Each row is one step" in out["row"] and 'class="fdot critical"' in out["row"] and "the whole note" in out["row"] and 'class="full"' in out["row"]


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
def test_the_script_list_is_the_layout_scripts_and_choosing_one_asks_the_server_to_switch(tmp_path):
    out = run_page(tmp_path, r"""
const scripts = [{id: "m/A_layout.py", title: "A", subtitle: "first", current: true}, {id: "m/B_layout.py", title: "B", subtitle: "", current: false}];
send("hello", {script: "A_layout.py", title: "A", subtitle: "first board", scripts, keep: 5, history: [], resolving: null, error: null});
send("started", {id: 1, script: "A_layout.py", at: 0, texts: {"A_layout.py": "board.place()\n", "core_geometry.py": "def f(): pass\n", "placemat.toml": ""}, changed: [], stale_files: []});
out.title = [els["#board-title"].textContent, els["#board-sub"].textContent];
out.options = els["#file"].innerHTML;
els["#file"].handlers.change[0]({target: {value: "L:m/B_layout.py"}});
out.fetched = fetched.map(([u, o]) => [u, o.method, o.body]);
send("switched", {script: "B_layout.py", title: "B", subtitle: "", scripts: scripts.map(s => Object.assign({}, s, {current: !s.current})), keep: 5, history: [], resolving: null, error: null});
out.after = [els["#board-title"].textContent, ev("S.docs.size"), ev("S.live"), ev("S.status")];
""")
    assert out["title"] == ["A", "first board"]
    assert "m/A_layout.py" in out["options"] and "m/B_layout.py" in out["options"] and "core_geometry" not in out["options"] and "placemat.toml" not in out["options"]
    assert out["fetched"] == [["/switch?t=x", "POST", '{"script":"m/B_layout.py"}']]
    assert out["after"] == ["B", 0, None, "waiting"]
