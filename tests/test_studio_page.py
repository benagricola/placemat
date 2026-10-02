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
const listeners = {}, frames = [];
const flush = () => { while (frames.length) frames.shift()(); };
const flushOnce = () => { frames.splice(0).forEach(f => f()); };
const ctx = {
  document: {querySelector: stub, querySelectorAll: () => [], body: {dataset: {}}, elementFromPoint: () => null},
  window: {addEventListener() {}}, location: {search: "?t=x"}, matchMedia: () => ({matches: true}), Date: FakeDate,
  EventSource: class { constructor() { this.addEventListener = (n, f) => { listeners[n] = f; }; } },
  requestAnimationFrame: f => { frames.push(f); }, setInterval() {}, clearInterval() {}, setTimeout() {}, fetch: () => Promise.reject(new Error("no")),
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
