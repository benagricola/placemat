"""The studio page: one static file, nothing fetched from outside, script that parses."""
from pathlib import Path
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


HARNESS = r"""
const vm = require("vm"), fs = require("fs");
const els = {};
const stub = sel => els[sel] || (els[sel] = new Proxy({
  innerHTML: "", textContent: "", value: "", style: {}, dataset: {}, className: "", attrs: {}, max: 0,
  classList: {toggle() {}, add() {}, remove() {}},
  addEventListener() {}, querySelectorAll: () => [], closest: () => null, setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k] || null; },
  getBoundingClientRect() { return {x: 0, y: 0, width: 412, height: 600, left: 0, top: 0}; },
}, {get: (o, k) => k in o ? o[k] : undefined}));
const listeners = {}, frames = [];
const flush = () => { while (frames.length) frames.shift()(); };
const ctx = {
  document: {querySelector: stub, querySelectorAll: () => [], body: {dataset: {}}, elementFromPoint: () => null},
  window: {addEventListener() {}}, location: {search: "?t=x"}, matchMedia: () => ({matches: true}),
  EventSource: class { constructor() { this.addEventListener = (n, f) => { listeners[n] = f; }; } },
  requestAnimationFrame: f => { frames.push(f); }, setInterval() {}, clearInterval() {}, setTimeout() {}, fetch: () => Promise.reject(new Error("no")),
  URLSearchParams, console,
};
ctx.window.matchMedia = ctx.matchMedia;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx);
flush();
const send = (name, data) => { listeners[name]({data: JSON.stringify(data)}); flush(); };
const board = () => els["#board"];
const out = {};
send("hello", {script: "x_layout.py", keep: 5, history: [], resolving: 1, error: null});
send("started", {id: 1, script: "x_layout.py", at: 0, texts: {"x_layout.py": "a\n", "placemat.toml": "b\n"}, changed: [], stale_files: []});
out.before_board = board().innerHTML;
send("board", {id: 1, board: {extent: [0, 0, 10, 8], loops: [[[0, 0], [10, 0], [10, 8], [0, 8]]], drawn: true}, keepouts: [], reservations: []});
out.after_board = board().innerHTML;
out.viewbox = board().getAttribute("viewBox");
const shape = (kind, poly) => ({kind, poly, faces: ["front"]});
const item = (key, x) => ({key, kind: "cell", placed: true, face: "front", rotation: 0, note: "", how: "", freedom: "decided",
  members: [{ref: "R" + key, value: "", cell: key, shapes: [shape("courtyard", [[x, 1], [x + 2, 1], [x + 2, 3]]), shape("pad", [[x, 1], [x + 1, 1], [x + 1, 2]])]}]});
send("step", {id: 1, item: item("a", 1)});
out.one = board().innerHTML;
send("step", {id: 1, item: item("b", 5)});
out.two = board().innerHTML;
out.steps = els["#tab-steps"].innerHTML;
out.files = els["#file"].innerHTML;
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_board_is_drawn_as_it_arrives_during_a_resolve(tmp_path):
    """Run the page's script against a DOM stub: the outline shows when `board` arrives, each `step` adds its
    shapes, and the view is set to the board; the file select lists the Python files only."""
    import json
    text = PAGE.read_text()
    (tmp_path / "page.js").write_text(text[text.index("<script>") + 8:text.index("</script>")])
    (tmp_path / "run.js").write_text(HARNESS)
    done = subprocess.run(["node", str(tmp_path / "run.js"), str(tmp_path / "page.js")], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert "<path" not in out["before_board"]
    assert "<path" in out["after_board"] and out["viewbox"]
    assert 'data-key="a"' in out["one"] and "<polygon" in out["one"] and 'data-key="b"' not in out["one"]
    assert 'data-key="a"' in out["two"] and 'data-key="b"' in out["two"]
    assert 'data-i="0"' in out["steps"] and 'data-i="1"' in out["steps"]
    assert "x_layout.py" in out["files"] and "placemat.toml" not in out["files"]


def test_the_layout_gives_a_narrow_screen_one_panel_at_the_full_width():
    text = PAGE.read_text()
    assert "minmax(0, 1fr)" in text and 'id="ntabs"' in text
    narrow = text[text.index("@media (max-width: 900px)"):text.index("</style>")]
    assert "grid-template-columns: 1fr;" not in narrow
