"""The 3D viewer's pure parts, run in node: the mesh file read by the page against the one python writes, and the visible set at a replay step,
which must be the set the 2D drawing shows."""
import json
import re
import shutil
import subprocess
from array import array
from pathlib import Path

import pytest

import placemat
from placemat import model_mesh as mm

CORE = Path(placemat.__file__).with_name("studio_3d_core.js")
PAGE = Path(placemat.__file__).with_name("studio_page.html")
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def node(script: str, tmp_path: Path):
    f = tmp_path / "t.mjs"
    f.write_text(script)
    done = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@needs_node
def test_the_page_reads_the_mesh_file_python_writes_whatever_its_index_width(tmp_path):
    big = 70000
    pos = array("f", [(i % 97) * 0.5 for i in range(3 * big)])
    mesh = mm.Mesh([mm.Material((10, 20, 30), 1.0, array("f", [0, 0, 0, 1, 0, 0, 0, 2, 0.5]), array("f", [0, 0, 1] * 3), array("I", [0, 1, 2])),
                    mm.Material((200, 100, 50), 0.5, pos, array("f", [0.0] * 3 * big), array("I", [0, 1, big - 1, 5, 6, 7]))])
    (tmp_path / "m.pmm").write_bytes(mm.write_pmm(mesh))
    out = node('''
        import { readFileSync } from "node:fs";
        import { parsePmm } from "%s";
        const b = readFileSync("%s"); const buf = b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength);
        const m = parsePmm(buf);
        console.log(JSON.stringify({tris: m.header.tris, bbox: m.header.bbox, n: m.mats.length, c0: m.mats[0].colour, o1: m.mats[1].opacity,
          p0: Array.from(m.mats[0].pos), i0: Array.from(m.mats[0].idx), i1: Array.from(m.mats[1].idx), p1: Array.from(m.mats[1].pos.slice(0, 6)), ib: m.mats.map(x => x.idx.BYTES_PER_ELEMENT)}));
    ''' % (CORE, tmp_path / "m.pmm"), tmp_path)
    assert out["n"] == 2 and out["c0"] == [10, 20, 30] and out["o1"] == 0.5 and out["ib"] == [2, 4]
    assert out["p0"] == [0, 0, 0, 1, 0, 0, 0, 2, 0.5] and out["i0"] == [0, 1, 2] and out["i1"] == [0, 1, big - 1, 5, 6, 7] and out["p1"] == [0, 0.5, 1.0, 1.5, 2.0, 2.5]
    assert out["tris"] == 3 and out["bbox"][3] == pytest.approx(48.0)


@needs_node
def test_a_file_that_is_not_a_mesh_is_refused_by_the_page_too(tmp_path):
    out = node('''
        import { parsePmm } from "%s";
        let msg = "";
        try { parsePmm(new ArrayBuffer(40)); } catch (e) { msg = String(e.message); }
        console.log(JSON.stringify({msg}));
    ''' % CORE, tmp_path)
    assert out["msg"] == "not a placemat mesh"


def _page_function(name: str) -> str:
    """The source of a top-level `function name(...) {...}` or `const name = ...;` of the page's script."""
    text = PAGE.read_text()
    m = re.search(r"^(?:function %s\(|const %s = )" % (name, name), text, re.M)
    assert m, name
    start, depth, i = m.start(), 0, m.start()
    if text[start:].startswith("function"):
        i = text.index("{", start)
        depth = 0
        while True:
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
            if depth == 0:
                break
        return text[start:i]
    return text[start:text.index("\n", start)]


@needs_node
def test_the_3d_view_shows_at_each_replay_step_the_parts_the_2d_drawing_shows(tmp_path):
    pieces = "\n".join(_page_function(n) for n in ("clamp", "isDrawn", "itemsOf", "replaySteps", "itemsAtStep"))
    out = node('''
        import { visibleKeys } from "%s";
        %s
        const shape = [{kind: "courtyard", faces: ["front"], poly: [[0, 0], [1, 0], [1, 1]]}];
        const item = k => ({key: k, members: [{ref: k, shapes: shape}]});
        const noShape = k => ({key: k, members: [{ref: k, shapes: []}]});
        const plan = {items: [item("a"), item("b"), noShape("setup"), item("c"), item("d")],
          steps: [{item: "setup", kind: "keepout"}, {item: "a", kind: "part"}, {item: "b", kind: "part"}, {item: "net1", kind: "copper"}, {item: "c", kind: "part"},
                  {item: "a", kind: "part"}, {item: "cut", kind: "cutout"}, {item: "d", kind: "part"}]};
        const order = replaySteps(plan), res = [];
        for (let k = -1; k <= order.length + 2; k++) res.push([k, visibleKeys(plan, order, k), itemsAtStep(plan, k)]);
        res.push(["all", visibleKeys(plan, order, null), itemsAtStep(plan, null)]);
        console.log(JSON.stringify({res, n: order.length}));
    ''' % (CORE, pieces), tmp_path)
    assert out["n"] == 6 and len(out["res"]) == 11
    for k, ours, theirs in out["res"]:
        assert ours == theirs, k
    assert out["res"][-1][1] == ["a", "b", "c", "d"] and out["res"][2][1] == ["a"]
