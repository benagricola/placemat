"""Two footprints that share a reference: a connection's ends are told apart by the footprint's own identity (KiCad's
footprint uuid), so each is judged on its own copper."""
import json
from dataclasses import replace

from placemat.kicad import phase_run
from tests.conftest import needs_kicad
from tests.fixtures import board_geometry, footprint

A, B, J = "00000000-0000-0000-0000-00000000000a", "00000000-0000-0000-0000-00000000000b", \
    "00000000-0000-0000-0000-00000000000c"


def _board(tmp_path):
    """Two TP4s and J1, each with pad 1 on VB; a track joins the second TP4 to J1, the first is left open."""
    def part(ref, x, uuid, pad_uuid):
        return ('\t(footprint "t:p" (layer "F.Cu") (uuid "%s") (at %g 110)\n\t\t(property "Reference" "%s" (at 0 -2 0) '
                '(layer "F.SilkS"))\n\t\t(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu" "F.Mask") (net 1 "VB") '
                '(uuid "%s"))\n\t)\n' % (uuid, x, ref, pad_uuid))
    pcb = tmp_path / "layout.kicad_pcb"
    pcb.write_text('(kicad_pcb\n\t(version 20241229)\n\t(generator "test")\n\t(general (thickness 1.6))\n'
                   '\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(2 "B.Cu" signal)\n\t\t(25 "Edge.Cuts" user)\n'
                   '\t\t(1 "F.Mask" user)\n\t\t(5 "F.SilkS" user)\n\t)\n\t(net 0 "")\n\t(net 1 "VB")\n'
                   + part("TP4", 110, A, A[:-2] + "1a") + part("TP4", 120, B, B[:-2] + "1b")
                   + part("J1", 130, J, J[:-2] + "1c")
                   + '\t(segment (start 120 110) (end 130 110) (width 0.4) (layer "F.Cu") (net 1))\n'
                   + '\t(gr_rect (start 100 100) (end 140 120) (stroke (width 0.1) (type solid)) (fill no) '
                     '(layer "Edge.Cuts"))\n)\n')
    return pcb


@needs_kicad
def test_each_footprint_of_a_shared_reference_is_judged_on_its_own_copper(tmp_path):
    pcb = _board(tmp_path)
    drc = tmp_path / "drc.json"
    drc.write_text(json.dumps({"violations": [], "unconnected_items": [
        {"items": [{"uuid": A[:-2] + "1a", "pos": {"x": 110, "y": 110}},
                   {"uuid": J[:-2] + "1c", "pos": {"x": 130, "y": 110}}]}]}))
    # the first TP4's island links to the nearest pad of the other island, the second TP4's
    (open_one,) = phase_run.open_connections(pcb, drc)
    assert open_one["from"] == {"ref": "TP4", "pad": "1", "fp": A}
    assert open_one["to"] == {"ref": "TP4", "pad": "1", "fp": B}
    joined_one = dict(open_one, **{"from": {"ref": "J1", "pad": "1"}})
    assert phase_run.joined_pairs(pcb, [(("J1", "1"), ("TP4", "1", A)), (("J1", "1"), ("TP4", "1", B))]) == \
        [False, True]
    obs = [dict(open_one, widths={"F.Cu": 0.4}), dict(joined_one, widths={"F.Cu": 0.4})]
    got = phase_run.judge_obligations(pcb, obs, drc, is_real=lambda _: True)
    assert [j["joined"] for j in got] == [False, True]
    assert got[1] == {"joined": True, "violated": False, "under": {}}


def test_a_joining_path_ends_at_the_footprint_its_end_names():
    from tests.test_route_widths_board import _track
    a = replace(footprint("TP4", 5.6 + 1.0, 10.0, nets=("V", "X")), uuid="fp-a")
    b = replace(footprint("TP4", 5.6 + 1.0, 20.0, nets=("V", "X")), uuid="fp-b")
    j = footprint("J1", 40.0 + 1.4, 10.0, nets=("V", "Y"))
    g = board_geometry([a, b, j], copper=[_track((5.2, 10), (40, 10), 0.5)], width=60, height=30)
    ob = {"net": "V", "from": {"ref": "TP4", "pad": "1", "fp": "fp-a"}, "to": {"ref": "J1", "pad": "1"}}
    assert phase_run.joining_spans(g, ob) is not None
    assert phase_run.joining_spans(g, dict(ob, **{"from": {"ref": "TP4", "pad": "1", "fp": "fp-b"}})) is None


def _shared_board():
    """J1 and two TP4s, each with pad 1 on VB and a stated current."""
    amps = {"Pm.I": "2A"}
    return board_geometry([footprint("J1", 25, 25, nets=("VB", ""), fields=amps),
                           replace(footprint("TP4", 5, 5, nets=("VB", ""), fields=amps), uuid="fp-a"),
                           replace(footprint("TP4", 15, 15, nets=("VB", ""), fields=amps), uuid="fp-b")])


def _select(raw, g):
    from placemat.kicad.phase_select import select
    from placemat.route_phase import parse_phases
    return select(parse_phases([raw])[0], g, None, open_nets={"VB"}, excluded=set(), pour_nets=set(),
                  route_layers=["F.Cu", "B.Cu"], rise_c=10, copper_oz=1)


def test_a_connection_to_a_shared_reference_is_a_task_to_each_footprint(tmp_path):
    sel = _select({"name": "c", "width": 0.5, "connections": [{"from": {"part": "J1", "pad": "1"},
                                                                "to": {"part": "TP4", "pad": "1"}}]}, _shared_board())
    assert sorted((t.start, t.end) for t in sel.tasks) == [(("J1", "1"), ("TP4", "1", "fp-a")),
                                                           (("J1", "1"), ("TP4", "1", "fp-b"))]
    written = json.loads(phase_run.write_connections(sel.tasks, tmp_path / "c.json", ["F.Cu", "B.Cu"]).read_text())
    assert [(w["from"], w["to"]) for w in written] == [({"ref": "J1", "pad": "1"}, {"ref": "TP4", "pad": "1", "fp": "fp-a"}),
                                                       ({"ref": "J1", "pad": "1"}, {"ref": "TP4", "pad": "1", "fp": "fp-b"})]
    (asked,) = phase_run.obligations_of([sel], [], set())
    assert [o["to"].get("fp") for o in asked] == ["fp-a", "fp-b"]


def test_current_paths_take_each_footprint_of_a_shared_reference_as_a_carrier():
    sel = _select({"name": "p", "current_paths": True}, _shared_board())
    assert sorted((t.start, t.end) for t in sel.tasks) == [(("J1", "1"), ("TP4", "1", "fp-a")),
                                                           (("J1", "1"), ("TP4", "1", "fp-b")),
                                                           (("TP4", "1", "fp-a"), ("TP4", "1", "fp-b"))]


def test_an_ordinary_boards_connections_file_names_no_footprint(tmp_path):
    g = board_geometry([footprint("J1", 25, 25, nets=("VB", "")), footprint("TP4", 5, 5, nets=("VB", ""))])
    sel = _select({"name": "c", "width": 0.5, "connections": [{"from": {"part": "J1", "pad": "1"},
                                                                "to": {"part": "TP4", "pad": "1"}}]}, g)
    written = phase_run.write_connections(sel.tasks, tmp_path / "c.json", ["F.Cu", "B.Cu"]).read_text()
    assert written == json.dumps([{"net": "VB", "from": {"ref": "J1", "pad": "1"}, "to": {"ref": "TP4", "pad": "1"},
                                   "widths": {"F.Cu": 0.5, "B.Cu": 0.5}}], indent=1) + "\n"


def test_each_task_on_a_shared_reference_takes_its_own_router_record():
    a = {"net": "VB", "from": {"ref": "J1", "pad": "1"}, "to": {"ref": "TP4", "pad": "1", "fp": "fp-a"}}
    b = dict(a, to={"ref": "TP4", "pad": "1", "fp": "fp-b"})
    plain = [dict(a, to={"ref": "TP4", "pad": "1"}, status="routed"), dict(a, to={"ref": "TP4", "pad": "1"},
                                                                          status="joined_before")]
    assert [r["status"] for r in phase_run.records_of([a, b], plain)] == ["routed", "joined_before"]
    echoed = [dict(b, status="joined_before"), dict(a, status="routed")]   # a router that echoes "fp"
    assert [r["status"] for r in phase_run.records_of([a, b], echoed)] == ["routed", "joined_before"]
    report = phase_run.phase_record(type("P", (), {"record": lambda self: {"name": "c"}, "max_uncoupled_mm": None})(),
                                    0, None, [a, b],
                                    [{"joined": False, "violated": False, "under": {}}] * 2, 1.0, 1,
                                    connections=plain)
    assert [o["outcome"] for o in report["open"]] == ["routed", "joined_before"]


def _task(fp, width=0.5):
    from placemat.kicad.phase_select import Task
    return Task("VB", ("J1", "1"), ("TP4", "1", fp), (("F.Cu", width),))


def _plain(task, status):
    return {"net": task.net, "from": {"ref": "J1", "pad": "1"}, "to": {"ref": "TP4", "pad": "1"},
            "widths": dict(task.widths), "status": status}


def test_a_task_stated_twice_does_not_shift_the_records_of_the_tasks_after_it():
    sent = [_task("fp-a"), _task("fp-a"), _task("fp-b")]
    recs = phase_run.answered(sent, [_plain(sent[0], "routed"), _plain(sent[1], "joined_before"),
                                     _plain(sent[2], "failed")])
    asked = phase_run._unique([dict(t.record(), widths=dict(t.widths)) for t in sent])
    assert [r["status"] for r in phase_run.records_of(asked, recs)] == ["routed", "failed"]


def test_shared_reference_tasks_split_across_calls_take_their_own_records():
    a, b = _task("fp-a", 0.3), _task("fp-b", 0.8)          # b goes in the first call (widest first), a in the second
    recs = phase_run.answered([b], [_plain(b, "routed")]) + phase_run.answered([a], [_plain(a, "failed")])
    asked = [dict(a.record(), widths=dict(a.widths)), dict(b.record(), widths=dict(b.widths))]
    assert [r["status"] for r in phase_run.records_of(asked, recs)] == ["failed", "routed"]


def test_a_router_record_keeps_what_it_said_of_each_end():
    t = _task("fp-a")
    rec = dict(_plain(t, "failed"), to={"ref": "TP4", "pad": "1", "at": [1.0, 2.0]})
    (got,) = phase_run.answered([t], [rec])
    assert got["to"] == {"ref": "TP4", "pad": "1", "at": [1.0, 2.0], "fp": "fp-a"}
    assert got["from"] == {"ref": "J1", "pad": "1"}
