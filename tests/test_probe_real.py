"""The probe on a real fixture module (usb5v, staged as a copy): the unedited script and each candidate are resolved by
`probe.overlay_resolver` (previewer.resolved with the candidate's text read in place of the file, the last record replayed), and
`placemat apply <id> --search` runs it from the command line. The searched suggestion is made by hand from a real finding's
instant one (a link's weight as a set), so this checks the machinery on a real board; the builders' figures are in
test_probe_synthetic."""
import json
from dataclasses import replace

import pytest

from placemat import cli, probe, suggestions as sg
from tests import real_modules as rm
from tests.conftest import needs_kicad
from tests.suggest_support import suggestions_of

pytestmark = needs_kicad

MODULE = "usb5v"
OVER = '\nboard.link(PadRef(Part("c_hf1"), "VSHUNT"), PadRef(Part("buck"), VIN_N), limit_mm=0.01)\n'


def layout_of(tmp_path):
    return tmp_path / "board" / "modules" / MODULE / "Usb5v_layout.py"


@pytest.fixture(scope="module")
def staged(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("probe_real")
    result, drc, pcb = rm.run(tmp, MODULE, keep_going=True, edit=lambda t: t + OVER)
    (f,) = [f for f in result.plan.findings if f.cause.value == "link_over"]
    limit = next(s for s in f.suggestions if s.lever == "limit")
    far = limit.edits[0].value["const"]["value"]
    figure = {"name": "limit", "unit": "mm", "kind": "bisect", "edit": 0, "declared": f.facts["limit_mm"], "far": far,
              "lo": f.facts["limit_mm"], "hi": far, "direction": "higher clears", "resolution": 0.01, "what": "the link's limit",
              "const": "C_HF1_LINK_LIMIT_MM", "of": "achieved_mm", "times": 1, "finding": list(sg.finding_key(f)),
              "severity": f.severity}
    searched = replace(limit, edits=(replace(limit.edits[0], value=None),), how="searched", figure=figure, id="s1z",
                       text="Changing the link's limit might fix this: search options?")
    layout = layout_of(tmp)
    sg.keep(layout.parent, layout, "run test", [searched])
    return tmp, layout, searched, far


def test_the_probe_resolves_each_candidate_from_the_overlay_and_writes_nothing(staged):
    tmp, layout, s, far = staged
    text = layout.read_text()
    from placemat.settings import load
    cfg = load(layout.parent, script=layout)
    events = []
    result, found = probe.search(s, layout.parent, layout, cfg, emit=events.append)
    assert result.state == "found" and result.best.value == pytest.approx(far, abs=0.011) and result.n <= 12
    assert [e["ev"] for e in events][0] == "probe" and events[-1]["ev"] == "probe_done"
    assert all(e["seconds"] > 0 for e in events if e["ev"] == "candidate")
    assert layout.read_text() == text and not (layout.parent / ".placemat" / "applied.jsonl").exists()
    assert found.id == "s1z.1" and "C_HF1_LINK_LIMIT_MM" in json.dumps(found.to_json())
    saved = probe.load_results(probe.results_path(layout.parent, s))
    assert len(saved) == result.n


def test_the_command_line_runs_it_and_a_second_run_resolves_nothing_again(staged, capsys):
    tmp, layout, s, far = staged
    saved = len(probe.load_results(probe.results_path(layout.parent, s)))
    code = cli.main(["apply", "s1z", "--script", str(layout), "--search", "--yes"])
    out = capsys.readouterr().out
    assert code == 0 and "continuing s1z from %d saved result(s)" % saved in out and out.count(", saved)") == saved
    code = cli.main(["apply", "s1z.1", "--script", str(layout), "--dry-run"])
    assert code == 0 and "C_HF1_LINK_LIMIT_MM" in capsys.readouterr().out
