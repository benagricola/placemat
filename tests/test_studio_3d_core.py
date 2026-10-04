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


@needs_node
def test_a_part_with_no_model_is_a_plate_of_its_courtyard_else_its_body_else_the_box_of_its_shapes(tmp_path):
    out = node('''
        import { plateOutline } from "%s";
        const sq = (x, y, w) => [[x, y], [x + w, y], [x + w, y + w], [x, y + w]];
        const it = {key: "cell", at: [50, 50], face: "front"};
        const court = {shapes: [{kind: "courtyard", faces: ["back"], poly: sq(0, 0, 3)}, {kind: "body", faces: ["front"], poly: sq(10, 10, 1)}]};
        const body = {shapes: [{kind: "silk", faces: ["front"], poly: sq(0, 0, 9)}, {kind: "body", faces: ["back"], poly: sq(10, 10, 2)}]};
        const pads = {shapes: [{kind: "pad", faces: ["back"], poly: sq(20, 20, 1)}, {kind: "pad", faces: ["back"], poly: sq(23, 20, 1)}]};
        const none = {shapes: []};
        console.log(JSON.stringify([court, body, pads, none].map(m => plateOutline(it, m))));
    ''' % CORE, tmp_path)
    assert out[0] == {"pts": [[0, 0], [3, 0], [3, 3], [0, 3]], "back": True}
    assert out[1] == {"pts": [[10, 10], [12, 10], [12, 12], [10, 12]], "back": True}
    assert out[2] == {"pts": [[20, 20], [24, 20], [24, 21], [20, 21]], "back": True}                     # the box of its pads, on their face
    assert out[3] == {"pts": [[49.4, 49.4], [50.6, 49.4], [50.6, 50.6], [49.4, 50.6]], "back": False}      # nothing to draw: a marker at the item


@needs_node
def test_the_copper_layers_stand_at_the_stackups_heights_or_evenly_spaced_without_one(tmp_path):
    out = node('''
        import { layerStack, drawHeight } from "%s";
        const declared = {stackup: {thickness: 1.6, declared: true, layers: [{name: "F.Cu", z: 1.5725, thickness: 0.035}, {name: "In1.Cu", z: 1.4375, thickness: 0.035},
                          {name: "B.Cu", z: 0.0275, thickness: 0.035}]}};
        const bare = {layers: ["B.Cu", "In2.Cu", "F.Cu", "In1.Cu"], copper: []};
        const fromOps = {copper: [{t: "track", layer: "B.Cu"}, {t: "via", layers: []}, {t: "track", layer: "F.Cu"}, {t: "text"}]};
        const s = layerStack(declared);
        console.log(JSON.stringify({s, bare: layerStack(bare), ops: layerStack(fromOps), none: layerStack({}),
          drawn: s.layers.map(l => drawHeight(s, l.name)), gone: drawHeight(s, "In7.Cu")}));
    ''' % CORE, tmp_path)
    assert out["s"] == {"T": 1.6, "declared": True, "layers": [{"name": "F.Cu", "z": 1.5725, "t": 0.035}, {"name": "In1.Cu", "z": 1.4375, "t": 0.035}, {"name": "B.Cu", "z": 0.0275, "t": 0.035}]}
    assert [(l["name"], l["z"]) for l in out["bare"]["layers"]] == [("F.Cu", 1.6), ("In1.Cu", 1.0667), ("In2.Cu", 0.5333), ("B.Cu", 0)] and out["bare"]["declared"] is False
    assert [(l["name"], l["z"]) for l in out["ops"]["layers"]] == [("F.Cu", 1.6), ("B.Cu", 0)]
    assert out["none"]["layers"] == [] and out["none"]["T"] == 1.6
    assert out["drawn"] == [1.6, 1.4375, 0] and out["gone"] is None          # the outer layers are drawn on the board's faces


@needs_node
def test_spreading_pulls_the_layers_apart_about_the_middle_and_the_parts_ride_on_the_outer_ones(tmp_path):
    out = node('''
        import { layerStack, spreadHeight, spreadLift } from "%s";
        const s = layerStack({stackup: {thickness: 1.6, layers: [{name: "F.Cu", z: 1.57}, {name: "In1.Cu", z: 1.0}, {name: "In2.Cu", z: 0.6}, {name: "B.Cu", z: 0.03}]}});
        const at = k => s.layers.map(l => +spreadHeight(s, l.name, k, 4).toFixed(4));
        console.log(JSON.stringify({closed: at(0), half: at(0.5), open: at(1), lift: [spreadLift(s, 1, 4), spreadLift(s, 0, 4), spreadLift(layerStack({stackup: {thickness: 1, layers: [{name: "F.Cu", z: 1}]}}), 1, 4)]}));
    ''' % CORE, tmp_path)
    assert out["closed"] == [1.6, 1.0, 0.6, 0]
    assert out["open"] == [7.6, 3.0, -1.4, -6.0]                 # each layer 4 mm further from the next, the middle where it was
    assert out["half"] == [4.6, 2.0, -0.4, -3.0]
    assert out["lift"] == [6, 0, 0]                               # front parts rise with the top layer, back parts sink with the bottom one


@needs_node
def test_a_track_is_a_ribbon_with_round_ends_and_an_arc_is_a_chain_of_them(tmp_path):
    out = node('''
        import { trackPolys } from "%s";
        const area = p => Math.abs(p.reduce((s, q, i) => { const r = p[(i + 1) %% p.length]; return s + q[0] * r[1] - r[0] * q[1]; }, 0)) / 2;
        const straight = trackPolys({a: [0, 0], b: [10, 0], width: 2}, 16);
        const dot = trackPolys({a: [5, 5], b: [5, 5], width: 1}, 16);
        const arc = trackPolys({a: [10, 0], b: [0, 10], mid: [7.0711, 7.0711], arc: [10, 0, 1], width: 0.5}, 8);
        const far = arc.flat().map(q => Math.hypot(q[0], q[1]));
        console.log(JSON.stringify({n: straight.length, area: area(straight[0]), xs: [Math.min(...straight[0].map(q => q[0])), Math.max(...straight[0].map(q => q[0]))],
          ys: [Math.min(...straight[0].map(q => q[1])), Math.max(...straight[0].map(q => q[1]))], dot: dot.length && area(dot[0]), arcN: arc.length, rmin: Math.min(...far), rmax: Math.max(...far)}));
    ''' % CORE, tmp_path)
    assert out["n"] == 1 and out["xs"] == pytest.approx([-1, 11]) and out["ys"] == pytest.approx([-1, 1])
    assert out["area"] == pytest.approx(20 + 3.14159, rel=0.02)            # the rectangle and the two half discs
    assert out["dot"] == pytest.approx(3.14159 * 0.25, rel=0.03)
    assert out["arcN"] >= 6 and out["rmin"] == pytest.approx(9.75, abs=0.02) and out["rmax"] == pytest.approx(10.25, abs=0.02)


@needs_node
def test_copper_at_a_replay_step_is_what_the_2d_drawing_shows(tmp_path):
    out = node('''
        import { visibleRanges } from "%s";
        // three ops laid at steps 0, 2 and 3, the second ripped up again at step 4
        const spans = [{s: 0, x: null, i0: 0, i1: 6}, {s: 2, x: 4, i0: 6, i1: 12}, {s: 3, x: null, i0: 12, i1: 18}];
        const at = (k, laid) => visibleRanges(spans, k, 6, laid);
        console.log(JSON.stringify({all: at(null, false), end: at(6, true), mid: at(3, false), laid: [0, 1, 3, 4, 5].map(k => at(k, true))}));
    ''' % CORE, tmp_path)
    assert out["all"] == [[0, 6], [12, 18]] and out["end"] == [[0, 6], [12, 18]]      # the ripped op is gone once the replay is past it
    assert out["mid"] == []                                                          # a plan's replay draws no copper until its end, as 2D
    assert out["laid"] == [[], [[0, 6]], [[0, 12]], [[0, 18]], [[0, 6], [12, 18]]]   # a route's replay lays and rips each op at its step


@needs_node
def test_the_legends_switches_hide_the_copper_they_hide_in_2d(tmp_path):
    out = node('''
        import { copperShown } from "%s";
        const cus = {track: {kind: "track", layer: "In1.Cu", origin: "routed"}, zone: {kind: "zone", layer: "F.Cu", origin: "planned", zone: 4},
                     pad: {kind: "pad", layer: "B.Cu"}, fcu: {kind: "fcu", layer: "B.Cu"}, via: {kind: "via", origin: "kept"}};
        const offs = [[], ["cu:In1.Cu"], ["org:routed"], ["z:4"], ["cu:F.Cu"], ["org:planned"], ["pad"], ["cu:B.Cu"], ["via"], ["org:kept"], ["cu:In2.Cu", "org:planned"]];
        console.log(JSON.stringify(offs.map(o => [o, Object.fromEntries(Object.entries(cus).map(([k, cu]) => [k, copperShown(cu, new Set(o))]))])));
    ''' % CORE, tmp_path)
    hidden ={tuple(o): sorted(k for k, v in shown.items() if not v) for o, shown in out}
    assert hidden[()] == []
    assert hidden[("cu:In1.Cu",)] == ["track"] and hidden[("org:routed",)] == ["track"]
    assert hidden[("z:4",)] == ["zone"] and hidden[("cu:F.Cu",)] == ["zone"] and hidden[("org:planned",)] == ["zone"]
    assert hidden[("pad",)] == ["pad"] and hidden[("cu:B.Cu",)] == ["fcu", "pad"]       # the pad switch takes pads, not a part's own copper
    assert hidden[("via",)] == ["via"] and hidden[("org:kept",)] == ["via"] and hidden[("cu:In2.Cu", "org:planned")] == ["zone"]


@needs_node
def test_a_via_spans_its_layers_and_a_through_via_the_whole_stack(tmp_path):
    out = node('''
        import { viaSpan } from "%s";
        const names = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"];
        console.log(JSON.stringify([viaSpan({layers: []}, names), viaSpan({layers: ["In1.Cu", "F.Cu"]}, names), viaSpan({layers: ["In2.Cu", "In1.Cu"]}, names), viaSpan({layers: ["In9.Cu"]}, names)]));
    ''' % CORE, tmp_path)
    assert out == [["F.Cu", "B.Cu"], ["F.Cu", "In1.Cu"], ["In1.Cu", "In2.Cu"], ["F.Cu", "B.Cu"]]
