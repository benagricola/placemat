"""A probe run on a synthetic board whose script is a real file: the finding's own measurement gives the searched figure, each
candidate is a real resolve of the edited text (context.overlay), and the best candidate applied clears the finding."""
import json
import re

import pytest

from placemat import context, probe, suggestions as sg
from placemat.board_geometry import Footprint
from placemat.context import run_script
from placemat.findings import FindingCause as C
from placemat.layout import Board
from placemat.values import Box, Face, Location
from tests.fixtures import board_geometry, footprint, pad

IMPORTS = "from placemat import board, CopperLayer, Location, Net, PadRef, Part\n"
BODY = ('board.place(Part("u1"), at=Location(10, 10))\n'
        'board.track(Net("A"), [PadRef(Part("u1"), 1), (20.0, 10.0), (20.0, 20.0)], layer=CopperLayer.F, width=0.3)\n')


def _small_part(ref, cx, cy, net, size=0.2):
    p = pad(ref, ref.lower(), "1", net, cx, cy, size, size)
    body = Box(cx - size / 2, cy - size / 2, cx + size / 2, cy + size / 2)
    return Footprint(ref, ref.lower(), None, ref, Location(cx, cy), 0.0, Face.FRONT, body, body.inflate(0.1), body, (p,))


def _board(path):
    parts = [footprint("U1", 10, 10, nets=("A", "A")), _small_part("R1", 19.2, 10.8, "B")]
    b = Board(board_geometry(parts, width=40, height=40, clearance=0.2), edge_margin=0.5, keep_going=True)
    b.script_file = str(path)
    return b


def _resolved(path):
    b = _board(path)
    run_script(path, b)
    return b, b.resolve()


@pytest.fixture
def scene(tmp_path):
    path = tmp_path / "layout.py"
    path.write_text(IMPORTS + BODY)
    b, plan = _resolved(path)
    return tmp_path, path, b, plan


def resolve_in_place(path):
    def resolve(overlay):
        with context.overlay(overlay):
            b = _board(path)
            run_script(path, b)
            plan = b.resolve()
        return probe.Outcome(list(plan.findings), None, 0.0)
    return resolve


def _meets(plan):
    return [f for f in plan.findings if f.cause is C.COPPER_MEETS and f.facts.get("chamfer_hit")]


def test_a_clearance_hit_on_the_chamfers_cut_offers_the_chamfer_as_a_searched_figure(scene):
    tmp, path, b, plan = scene
    (f,) = _meets(plan)
    hit = f.facts["hit"]
    short = hit["need_mm"] - hit["gap_mm"]
    searched = [s for s in f.suggestions if s.how == "searched"]
    (s,) = [s for s in searched if s.figure["name"] == "chamfer"]
    fig = s.figure
    assert s.text == "Changing the chamfer of the A track might fix this: search options?"
    assert fig["kind"] == "bisect" and fig["declared"] == f.facts["chamfer_mm"] and fig["times"] == 2
    assert fig["far"] == pytest.approx(max(0.0, fig["declared"] - 2 * short), abs=0.011) and fig["far"] < fig["declared"]
    assert fig["of"] == "need_mm - gap_mm" and fig["finding"][1] == "copper.meets" and fig["direction"] == "lower clears"
    assert s.digests and s.edits[0].target.file == str(path) and s.edits[0].value is None
    again = sg.Suggestion.from_json(json.loads(json.dumps(s.to_json())))
    assert again.how == "searched" and again.figure == fig


def test_nothing_is_applied_from_a_searched_suggestion_without_a_value(scene):
    tmp, path, b, plan = scene
    (f,) = _meets(plan)
    s = next(s for s in f.suggestions if s.how == "searched")
    # the edit with no value would write `chamfer=None`: the probe is the way to a value, not apply
    done = sg.apply_edits(sg.fill(s.edits, s.figure, sg.sample_value(s.figure)), s.digests, dry_run=True)
    assert "chamfer=" in done.files[str(path)].after


def test_the_probe_finds_a_chamfer_that_clears_the_finding_and_the_result_applies(scene):
    tmp, path, b, plan = scene
    (f,) = _meets(plan)
    s = next(s for s in f.suggestions if s.how == "searched" and s.figure["name"] == "chamfer")
    base = probe.Outcome(list(plan.findings), None, 0.0)
    events = []
    r = probe.Probe(s, resolve_in_place(path), base, budget_s=600, candidates=12, emit=events.append).run()
    assert r.state == "found" and 0.0 <= r.best.value < s.figure["declared"]
    assert r.n <= 12 and path.read_text() == IMPORTS + BODY                   # the probe wrote nothing
    found = probe.found_suggestion(s, r)
    assert found.id == s.id + ".1" and found.how == "instant"
    sg.apply_edits(found.edits, found.digests, root=tmp, log=tmp / "applied.jsonl", label=found.text)
    text = path.read_text()
    assert re.search(r"CHAMFER_MM = [0-9.]+", text) and "chamfer=" in text and "Found by a probe" in text
    _, after = _resolved(path)
    assert not _meets(after)
    assert [e["ev"] for e in events][0] == "probe" and events[-1]["state"] == "found"
