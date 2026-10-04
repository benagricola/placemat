"""What the DRC headline counts: severity decides, and where the board sits explains library issues."""
import json
import os
import subprocess
import sys

from placemat.kicad import drc as D
from placemat.kicad.drc import DrcReport


def _viol(kind, severity="error", desc="d"):
    return {"type": kind, "severity": severity, "description": desc, "items": []}


def test_the_severity_of_each_kind_is_carried_structured():
    data = {"violations": [_viol("zones_intersect"), _viol("silk_overlap", "warning"),
                           _viol("clearance"), _viol("clearance", "warning")]}
    assert D.violation_severities(data, {}) == {"zones_intersect": "error", "silk_overlap": "warning", "clearance": "error"}


def test_an_error_of_any_kind_is_in_the_headline():
    r = DrcReport(path=None, by_type={"zones_intersect": 2, "silk_overlap": 3, "clearance": 1},
                  severities={"zones_intersect": "error", "silk_overlap": "warning", "clearance": "warning"})
    assert r.real == {"zones_intersect": 2, "clearance": 1}       # clearance: counted whatever its severity
    assert r.other == {"silk_overlap": 3}
    assert r.summary().startswith("DRC 1 clearance, 2 zones_intersect")


def test_footprint_and_outstanding_errors_keep_their_own_lines():
    r = DrcReport(path=None, by_type={"lib_footprint_issues": 4, "via_dangling": 1, "zones_intersect": 1},
                  severities={"lib_footprint_issues": "error", "via_dangling": "error", "zones_intersect": "error"})
    assert r.real == {"zones_intersect": 1}
    assert r.footprint_issues == {"lib_footprint_issues": 4} and r.outstanding == {"via_dangling": 1}
    assert r.other == {}


def test_without_severities_only_the_listed_kinds_count():
    r = DrcReport(path=None, by_type={"zones_intersect": 2, "clearance": 1})
    assert r.real == {"clearance": 1} and r.other == {"zones_intersect": 2}


def _table(path, uri):
    path.write_text('(fp_lib_table\n  (version 7)\n  (lib (name "X")(type "KiCad")(uri "%s")(options "")(descr ""))\n)\n' % uri)


def test_a_board_with_no_library_table_beside_it(tmp_path):
    t = D.library_table(tmp_path / "layout.kicad_pcb")
    assert t == D.LibraryTable(path=None, state="missing", unresolved=())


def test_library_entries_that_do_not_resolve_from_the_board(tmp_path):
    run = tmp_path / "a" / "b" / "run"
    run.mkdir(parents=True)
    _table(run / "fp-lib-table", "${KIPRJMOD}/../../x.pretty")
    t = D.library_table(run / "layout.kicad_pcb")
    assert t.state == "unresolved" and t.unresolved == ("X",) and t.path == run / "fp-lib-table"
    (tmp_path / "a" / "x.pretty").mkdir()
    assert D.library_table(run / "layout.kicad_pcb").state == "resolved"


def test_a_library_outside_the_project_variable_is_not_judged(tmp_path):
    _table(tmp_path / "fp-lib-table", "${KICAD9_FOOTPRINT_DIR}/X.pretty")
    assert D.library_table(tmp_path / "layout.kicad_pcb").state == "resolved"


def test_the_summary_says_library_issues_come_from_where_the_board_sits():
    lib = D.LibraryTable(path=None, state="missing", unresolved=())
    r = DrcReport(path=None, by_type={"lib_footprint_issues": 199}, libraries=lib)
    s = r.summary()
    assert "footprint issues 199" in s and "where the board sits" in s
    ok = DrcReport(path=None, by_type={"lib_footprint_issues": 3}, libraries=D.LibraryTable(None, "resolved", ()))
    assert "where the board sits" not in ok.summary()
    none = DrcReport(path=None, by_type={"silk_overlap": 1}, libraries=lib)
    assert "where the board sits" not in none.summary()


def test_run_drc_records_the_library_table_and_the_severity(tmp_path, monkeypatch):
    pcb = tmp_path / "layout.kicad_pcb"
    pcb.write_text("(kicad_pcb)")
    (tmp_path / "layout.kicad_pro").write_text("{}")
    out = tmp_path / "drc.json"

    class _Proc:
        returncode = 0
        stderr = ""

    def fake_run(cmd, **kw):
        out.write_text(json.dumps({"violations": [_viol("lib_footprint_issues"), _viol("zones_intersect")],
                                   "unconnected_items": []}))
        return _Proc()
    monkeypatch.setattr(D.subprocess, "run", fake_run)
    r = D.run_drc(pcb, out)
    assert r.libraries.state == "missing"
    assert r.severities["zones_intersect"] == "error" and r.real == {"zones_intersect": 1}


def test_a_child_does_not_see_a_kiprjmod_in_the_c_environment(monkeypatch):
    from placemat.childenv import child_env
    monkeypatch.delenv("KIPRJMOD", raising=False)
    os.putenv("KIPRJMOD", "/wrong")                  # the C environ only, as pcbnew leaves it
    try:
        code = "import os; print(repr(os.environ.get('KIPRJMOD')))"
        inherited = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True).stdout.strip()
        assert inherited == "'/wrong'"               # the premise: env=None passes it on
        via = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=child_env()).stdout.strip()
        assert via == "None"
    finally:
        os.unsetenv("KIPRJMOD")


def test_child_env_drops_an_inherited_kiprjmod_and_the_display_variables(monkeypatch):
    from placemat.childenv import child_env
    monkeypatch.setenv("KIPRJMOD", "/x")
    monkeypatch.setenv("DISPLAY", ":0")
    e = child_env()
    assert "KIPRJMOD" not in e and "DISPLAY" not in e
    e = child_env(headless=False, extra={"A": "1"})
    assert "KIPRJMOD" not in e and e["DISPLAY"] == ":0" and e["A"] == "1"


def test_every_kicad_child_is_started_with_the_shared_environment():
    import ast
    from pathlib import Path
    root = Path(D.__file__).parents[1]
    bare = []
    for p in root.rglob("*.py"):
        if p.name in ("previewer.py",) or p.parent.name == "pdf":       # an SVG converter and PDF tools, not KiCad
            continue
        for n in ast.walk(ast.parse(p.read_text())):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
                    and n.func.value.id == "subprocess" and n.func.attr in ("run", "Popen", "check_output", "call")):
                kw = {k.arg: k.value for k in n.keywords}
                v = kw.get("env")
                if v is None or (isinstance(v, ast.Constant) and v.value is None):
                    bare.append("%s:%d" % (p.relative_to(root), n.lineno))
    assert not bare, "started with the inherited environment: %s" % bare
