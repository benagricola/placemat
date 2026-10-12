"""A captured pair still routes when its counterpart is already joined."""
import hashlib
import pathlib
import shutil

from tests.conftest import needs_kicad, needs_router

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures/partly_joined_pair"


def test_the_static_capture_and_phases_name_the_existing_pair():
    from placemat.capture_nets import read_capture
    from placemat.route_phase import parse_phases
    import tomllib
    capture = read_capture(FIXTURE / "nets.layout.json")
    assert capture.pairs == (("USB.D", "USB_D_P", "USB_D_N"),)
    phases = parse_phases(tomllib.loads((FIXTURE / "placemat.toml").read_text())["route"]["phase"])
    assert [(p.name, p.selector) for p in phases] == [("diff-pairs", "pairs"), ("signals", "rest")]


def test_module_family_has_a_signal_fallback_and_a_module_selects_capture_pairs():
    import tomllib
    from placemat.route_phase import parse_phases
    family = ROOT / "fixtures/mnb"
    base = parse_phases(tomllib.loads((family / "placemat.toml").read_text())["route"]["phase"])
    usb = parse_phases(tomllib.loads((family / "modules/UsbC/placemat.toml").read_text())["route"]["phase"])
    assert [(p.name, p.selector) for p in base] == [("signals", "rest")]
    assert [(p.name, p.selector) for p in usb] == [("diff-pairs", "pairs"), ("signals", "rest")]


def _p_copper(path):
    import pcbnew
    board = pcbnew.LoadBoard(str(path))
    return sorted((track.GetLayerName(), track.GetStart().x, track.GetStart().y,
                   track.GetEnd().x, track.GetEnd().y, track.GetWidth(), track.IsLocked(), track.m_Uuid.AsString())
                  for track in board.GetTracks() if track.GetNetname() == "USB_D_P")


@needs_kicad
@needs_router
def test_an_actual_half_joined_pair_routes_without_changing_its_joined_leg(tmp_path):
    from fixtures.reference import lock, route_ref
    from placemat.kicad.drc import run_drc
    from placemat.kicad.phase_run import judge_obligations
    source = tmp_path / "input"
    shutil.copytree(FIXTURE, source)
    board = source / "pair.kicad_pcb"
    obligations = [{"net": net, "from": {"ref": "J1", "pad": str(i + 1)},
                    "to": {"ref": "J2", "pad": str(i + 1)}, "widths": None}
                   for i, net in enumerate(("USB_D_P", "USB_D_N"))]
    original = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir() if p.is_file()}
    with lock.realboard():
        initial_drc = tmp_path / "initial-drc.json"
        run_drc(board, initial_drc)
        initial = judge_obligations(board, obligations, initial_drc)
        assert [row["joined"] for row in initial] == [True, False]
        copper = _p_copper(board)
        report = route_ref._route(board, tmp_path / "route", (source / "placemat.toml").read_text())
        pair, signals = report["phases"]
        assert pair["name"] == "diff-pairs" and pair["calls"] > 0
        categories = pair["pairs"]
        name = "USB_D_P/USB_D_N"
        completed = [value for kind in ("coupled", "single_ended") for value in categories[kind]]
        assert completed.count(name) == 1, categories
        assert name not in categories["partial"] and name not in categories["failed"], categories
        assert signals["calls"] == 0
        # ruling S6: the phase's asked set is the input board's open connections on its nets; USB_D_P is joined there
        assert (pair["final_asked"], pair["final_joined"], pair["final_open"]) == (1, 1, [])
        final = pathlib.Path(report["routed_pcb"])
        final_drc = tmp_path / "final-drc.json"
        run_drc(final, final_drc)
        judged = judge_obligations(final, obligations, final_drc)
        assert all(row["joined"] and not row["violated"] for row in judged), (pair, signals, judged)
        assert _p_copper(final) == copper
        assert report["valid"] and report["drc_new"] == 0
        assert original == {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in original}
