"""Copper the router laid under the width it was asked: read from its per-stage summaries (kicad/route_widths.py), carried as records on
the report, as findings, in the summary line, in route_summary.json and on the channel.

tests/data/route_widths holds a real route's stage summaries (six island passes and the main pass), trimmed to the fields read."""
import json
from pathlib import Path

from placemat import channel, route_progress
from placemat.findings import FindingCause as C
from placemat.kicad.route import RouteReport
from placemat.kicad.route_widths import findings_of, read_widths, stage_widths

DATA = Path(__file__).parent / "data" / "route_widths"
ISLANDS = {"VSHUNT": 0.3, "VBIKE": None, "USB_HV": 1.37, "VBUS": 1.37, "GND": None, "V3V3": None}


def _report(widths):
    return RouteReport(True, 0.843, 0.843, 100, 16, {}, [], [], ["F.Cu"], 1.0, "v", {}, Path("r.kicad_pcb"), Path("r.log"), Path("."),
                       widths=widths)


def test_a_real_route_delivered_three_island_nets_under_width():
    records = read_widths(DATA, ISLANDS)
    got = {r["net"]: r for r in records}
    assert sorted(got) == ["USB_HV", "VBUS", "VSHUNT"] and all(r["stage"] == "islands" for r in records)
    usb = got["USB_HV"]
    assert (usb["requested_mm"], usb["delivered_min_mm"], usb["length_under_mm"], usb["length_mm"], usb["share"]) == (1.37, 0.16, 16.61, 17.24, 0.9636)
    assert (usb["max_a"], usb["bottleneck_mm"], usb["declared"]) == (0.45, 0.1, True)
    assert (got["VBUS"]["length_under_mm"], got["VBUS"]["length_mm"], got["VBUS"]["max_a"]) == (53.18, 107.83, 0.63)
    assert (got["VSHUNT"]["requested_mm"], got["VSHUNT"]["delivered_min_mm"], got["VSHUNT"]["length_under_mm"]) == (0.3, 0.1, 10.64)


def test_each_is_a_critical_finding_with_the_facts_and_the_sentence():
    found = findings_of(read_widths(DATA, ISLANDS), {"USB_HV": 3.0})
    assert [f.cause for f in found] == [C.ROUTE_WIDTH] * 3 and {f.severity for f in found} == {"critical"}
    usb = next(f for f in found if f.facts["net"] == "USB_HV")
    assert usb.facts["stated_a"] == 3.0 and usb.facts["max_a"] == 0.45 and usb.facts["share"] == 0.9636
    assert usb == ("net USB_HV: 16.6 of 17.2 mm (96%) of its copper in the islands stage is under the 1.37 mm it was asked, narrowest "
                   "0.16 mm; its narrowest copper carries 0.45 A at most, the design states 3 A")
    assert usb.line().startswith("[critical] net USB_HV")
    assert usb.detail()["cause"] == "route.width" and usb.detail()["facts"]["length_under_mm"] == 16.61


def test_a_net_the_script_gave_no_width_is_a_warning_unless_its_stated_current_is_over_what_the_copper_carries():
    summary = {"design_rules": {"narrowed": [{"net_name": "SIG", "kind": "track_width", "requested": 0.5, "delivered": 0.2,
                                              "site": "power copper shipped under width", "length_mm": 3.0}]},
               "power_trace_ampacity": [{"net": "SIG", "bottleneck_width_mm": 0.2, "max_current_a": 0.6}]}
    records = stage_widths("main", summary)
    assert records == [{"net": "SIG", "stage": "main", "requested_mm": 0.5, "delivered_min_mm": 0.2, "length_under_mm": 3.0,
                        "length_mm": None, "share": None, "declared": False, "max_a": 0.6, "bottleneck_mm": 0.2}]
    (plain,) = findings_of(records)
    assert plain.severity == "warning" and "net SIG: 3.0 mm of its copper in the main stage" in plain
    assert findings_of(records, {"SIG": 0.5})[0].severity == "warning"
    (over,) = findings_of(records, {"SIG": 2.0})
    assert over.severity == "critical" and over.endswith("carries 0.6 A at most, the design states 2 A")


def test_a_stage_that_kept_its_width_or_left_the_net_out_of_its_scope_gives_nothing():
    kept = {"power_widths": {"A": {"requested_mm": 0.3, "length_mm": 5.0, "under_mm": 0.0, "under_share": 0.0, "min_mm": 0.3,
                                   "in_run_scope": True},
                             "B": {"requested_mm": 0.3, "length_mm": 5.0, "under_mm": 2.0, "under_share": 0.4, "min_mm": 0.1,
                                   "in_run_scope": False}}}
    assert stage_widths("islands", kept) == [] and stage_widths("main", {}) == []
    assert read_widths(DATA / "nowhere", {"A": 0.3}) == []


def test_the_summary_line_and_the_report_carry_the_shortfall():
    clean = _report([])
    assert "UNDER WIDTH" not in clean.summary() and clean.as_dict()["widths"] == []
    short = _report(read_widths(DATA, ISLANDS))
    assert "UNDER WIDTH: USB_HV 16.6 of 17.2 mm under 1.37 (min 0.16); VBUS 53.2 of 107.8 mm under 1.37 (min 0.16)" in short.summary()
    assert short.as_dict()["widths"][0]["net"] == "USB_HV"
    assert len(short.findings({"USB_HV": 3.0})) == 3


def test_the_route_summary_file_and_the_watch_line_carry_it(tmp_path):
    widths = read_widths(DATA, ISLANDS)
    route_progress.write_record(tmp_path, {"pcb": "x.kicad_pcb", "run": "r", "script": "s.py"}, [], {"closure": 0.843, "widths": widths})
    doc = json.loads((tmp_path / "route_summary.json").read_text())
    assert [r["net"] for r in doc["under_width"]] == ["USB_HV", "VBUS", "VSHUNT"] and doc["closure"] == 0.843
    assert channel.describe(dict(widths[0], ev="route_width")) == "under its width in islands: USB_HV 16.6 of 17.2 mm under 1.37 (min 0.16)"
    assert channel.compact(dict(widths[0], ev="route_width"))["net"] == "USB_HV"


def test_the_route_command_prints_the_findings_and_json_carries_them(tmp_path, monkeypatch, capsys):
    from placemat import cli
    import placemat.kicad.read as read_mod
    import placemat.kicad.route as route_mod
    import placemat.kicad.route_widths as widths_mod
    pcb = tmp_path / "layout.kicad_pcb"
    pcb.write_text("")
    report = _report(read_widths(DATA, ISLANDS))
    report.open_nets = {}
    monkeypatch.setattr(route_mod, "route_board", lambda *a, **kw: report)
    monkeypatch.setattr(read_mod, "read_board", lambda p: "geometry")
    monkeypatch.setattr(widths_mod, "stated_currents", lambda g: {"USB_HV": 3.0})
    assert cli.main(["route", str(pcb)]) == 0
    out = capsys.readouterr().out
    assert "[critical] net USB_HV: 16.6 of 17.2 mm (96%)" in out and "the design states 3 A" in out and "UNDER WIDTH" in out
    assert cli.main(["route", str(pcb), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert [d["cause"] for d in doc["finding_details"]] == ["route.width"] * 3 and doc["widths"][0]["net"] == "USB_HV"
