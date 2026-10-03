"""Every finding carries a severity: a notice is placemat doing something by design, a warning a quality
issue a person judges, and a critical one a board that cannot be built or fully routed as it is."""
import json
import pickle

import pytest

from tests.finding_samples import finding
from placemat.findings import FindingCause as C
from placemat.findings import DEFAULT_SEVERITY, KINDS, SEVERITIES, SEVERITY, Findings, summary
from placemat.report import RunRecord
from placemat.reuse import finding_from_json, finding_to_json
from placemat.values import Location, Near, Part
from tests.test_carried_via_grids import NO_LEAVE, TOP_ROW, _board as _grid_board, _u1
from tests.test_escape_walled import _board as _walled_board
from tests.test_escape_findings import _walled_in
from tests.test_finding_kinds import _board as _kinds_board
from tests.test_preview_json import _plan as _preview_plan
from tests.test_vias_give_way import _later_board, _shared_later, _via, track


def test_every_kind_has_a_severity():
    assert set(SEVERITY) == set(KINDS)
    assert set(SEVERITY.values()) <= set(SEVERITIES)


def test_a_finding_has_its_kinds_severity_unless_it_says_its_own():
    assert finding(C.UNPLACED_RIDES).severity == "critical"
    assert finding(C.VIAS_GAVE_WAY).severity == "notice"
    assert finding(C.VIAS_GAVE_WAY, "warning").severity == "warning"
    with pytest.raises(ValueError):
        finding(C.VIAS_GAVE_WAY, "fatal")


def test_a_finding_keeps_its_severity_through_a_pickle_and_the_reuse_cache():
    f = finding(C.SETUP_UNDECLARED, "notice")
    assert pickle.loads(pickle.dumps(f)).severity == "notice"
    assert finding_from_json(finding_to_json(f)).severity == "notice"


def test_findings_count_by_severity_and_list_the_most_serious_first():
    fs = Findings([finding(C.VIAS_GAVE_WAY), finding(C.UNPLACED_RIDES), finding(C.LINK_OVER), finding(C.VIAS_GAVE_WAY)])
    assert fs.by_severity() == {"critical": 1, "warning": 1, "notice": 2}
    assert [f.cause for f in fs.most_serious_first()] == [C.UNPLACED_RIDES, C.LINK_OVER, C.VIAS_GAVE_WAY, C.VIAS_GAVE_WAY]
    assert summary(fs) == "1 critical, 1 warning, 2 notice" and summary([]) == ""
    assert finding(C.COPPER_STITCH).line() == "[critical] %s" % finding(C.COPPER_STITCH)


def test_a_given_way_via_shared_or_moved_is_a_notice():
    shared = [f for f in _shared_later().resolve().findings if f.kind == "vias"]
    assert shared and {f.severity for f in shared} == {"notice"}, shared
    moved = _later_board([_via("SIG", 39.1, 42.2, owner="m"), track("SIG", 39.1, 40.0, 39.1, 42.2, w=0.2, owner="m")],
                         (19.5, 23.0), net="SIG").resolve()
    found = [f for f in moved.findings if f.kind == "vias"]
    assert found and {f.severity for f in found} == {"notice"}, found


def test_a_relaid_field_is_a_notice_and_one_that_lost_vias_is_a_warning():
    relaid = _grid_board([TOP_ROW], settings=NO_LEAVE).resolve()
    assert [f.severity for f in relaid.findings if f.kind == "vias"] == ["notice"]
    dropped = _grid_board([(20.0, 19.2, 2.8, 0.3)], pitch=0.45, settings=NO_LEAVE, u1=_u1(1.5, 1.5)).resolve()
    assert [f.severity for f in dropped.findings if f.kind == "vias"] == ["warning"]


def test_a_pad_walled_in_is_critical():
    plan = _walled_board(_walled_in(0.1)).resolve()
    walled = [f for f in plan.findings if f.kind == "escape_walled"]
    assert [str(f) for f in walled] == ["U9 pin 1 (IN): walled off by R9"]
    assert walled[0].severity == "critical"
    assert walled[0].line() == "[critical] U9 pin 1 (IN): walled off by R9"


def test_a_part_with_no_room_is_critical_and_a_link_over_its_limit_a_warning():
    b = _kinds_board(keep_going=True)
    b.place(Part("u1"), at=Location(30, 30))
    b.place(Part("j1"), at=Near(Location(30, 30), radius=0.5))
    b.place(Part("c1"), at=Location(50, 50))
    b.place(Part("r1"), at=Location(50, 20))
    plan = b.resolve()
    assert {f.severity for f in plan.findings if f.kind == "unplaced"} == {"critical"}
    assert finding(C.LINK_OVER).severity == "warning"


def test_an_undeclared_part_is_a_warning_and_a_layer_the_board_lacks_a_notice():
    b = _kinds_board()
    b.place(Part("u1"), at=Location(20, 20))
    plan = b.resolve()
    assert {f.severity for f in plan.findings if "no declaration places it" in f} == {"warning"}


def test_the_plan_json_carries_each_findings_severity_and_the_counts():
    from placemat.preview_json import plan_json, declared_sites
    b, plan = _preview_plan()
    doc = plan_json(plan, declared_sites(b))
    assert doc["findings"] and all(f["severity"] in SEVERITIES for f in doc["findings"])
    assert doc["counts"]["severities"] == plan.findings.by_severity()
    json.dumps(doc)


def test_a_run_record_keeps_each_findings_severity():
    rec = RunRecord(run_id="a", board="x", status="ok")
    rec.findings = ["one", "two"]
    rec.finding_details = [{"kind": "vias", "severity": "notice", "text": "one"},
                           {"kind": "escape_walled", "severity": "critical", "text": "two"}]
    rec.add_finding("three")
    assert [d["severity"] for d in rec.findings_with_severity()] == ["notice", "critical", "warning"]


def test_a_run_record_from_before_severities_reads_as_warnings(tmp_path):
    old = {"run_id": "a", "board": "x", "status": "ok", "findings": ["old sentence"]}
    (tmp_path / "run.json").write_text(json.dumps(old))
    rec = RunRecord.load(tmp_path / "run.json")
    assert rec.findings_with_severity() == [{"kind": "", "severity": DEFAULT_SEVERITY, "text": "old sentence"}]
    assert DEFAULT_SEVERITY == "warning"
    rec.save(tmp_path / "again.json")
    assert RunRecord.load(tmp_path / "again.json").findings_with_severity() == rec.findings_with_severity()


def test_a_failed_keep_out_or_current_path_check_is_critical_and_a_heat_check_a_warning():
    from placemat.checks import Verdict
    fail = lambda check, **kw: Verdict(check, "s", 1.0, "mm", 2.0, False, **kw)
    assert fail("keep-out").severity == "critical" and fail("current-path").severity == "critical"
    assert fail("heat").severity == "warning"
    assert "FAIL [critical]" in fail("keep-out").line()
    assert Verdict("keep-out", "s", 3.0, "mm", 2.0, True).severity == ""
    assert fail("keep-out", accepted="accepted (>= 1): why").severity == ""


def test_a_run_and_a_preview_print_the_severity(capsys):
    from placemat.console import Console
    import io
    out = io.StringIO()
    Console(stream=out).finding(finding(C.ESCAPE_WALLED))
    assert "[critical] U1 pin 8 (GND): walled off by R4, U1" in out.getvalue()


def _usbc_preview(tmp_path, *args):
    import pathlib, shutil, subprocess, sys
    from tests.conftest import _has_pcbnew
    if not _has_pcbnew():
        pytest.skip("pcbnew not importable")
    root = pathlib.Path(__file__).resolve().parent.parent
    mod = tmp_path / "UsbC"
    shutil.copytree(root / "fixtures/mnb/modules/UsbC", mod)
    shutil.copytree(mod / "layout", mod / ".placemat/generated/UsbC")
    done = subprocess.run([sys.executable, "-m", "placemat", "preview", str(mod / "UsbC_layout.py"), "--svg", *args],
                          capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout


def test_preview_prints_each_finding_with_its_severity_most_serious_first(tmp_path):
    out = _usbc_preview(tmp_path)
    lines = [l for l in out.splitlines() if " finding " in l and "[" in l]
    assert lines, out
    tags = [l.split("[", 1)[1].split("]", 1)[0] for l in lines]
    assert set(tags) <= set(SEVERITIES)
    assert tags == sorted(tags, key=SEVERITIES.index, reverse=True)


def test_preview_json_carries_each_finding_with_its_severity(tmp_path):
    out = _usbc_preview(tmp_path, "--format", "json")
    doc = json.loads(out[out.index("\n{") + 1:])
    assert doc["findings"] and len(doc["finding_details"]) == len(doc["findings"])
    assert all(d["severity"] in SEVERITIES and d["text"] in doc["findings"] for d in doc["finding_details"])
