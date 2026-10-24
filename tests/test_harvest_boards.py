"""The rules of tools/harvest_boards.py that need no network: the licence list, path and repo filters, the choice of
boards in a repo, the routed check, the manifest's resume and the size-range search."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _tool():
    spec = importlib.util.spec_from_file_location("harvest_boards", ROOT / "tools/harvest_boards.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hb = _tool()


def test_open_licences_pass():
    for spdx in ("MIT", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0", "ISC", "MPL-2.0", "LGPL-3.0", "LGPL-2.1",
                 "GPL-3.0", "GPL-2.0", "AGPL-3.0", "CC-BY-4.0", "CC-BY-SA-4.0", "CC0-1.0", "Unlicense",
                 "CERN-OHL-P-2.0", "CERN-OHL-W-2.0", "CERN-OHL-S-2.0", "CERN-OHL-1.2"):
        assert hb.is_open_licence(spdx), spdx


def test_other_licences_fail():
    for spdx in (None, "", "NOASSERTION", "other", "CC-BY-NC-4.0", "CC-BY-NC-SA-4.0", "BSD-4-Clause-UC", "WTFPL",
                 "Proprietary", "OFL-1.1", "TAPR-OHL-1.0"):
        assert not hb.is_open_licence(spdx), spdx


def test_path_filter():
    assert hb.path_ok("hw/board/board.kicad_pcb")
    assert hb.path_ok("Calibrated/Latest/main.kicad_pcb")
    assert not hb.path_ok("hw/board/board.kicad_sch")
    for bad in ("templates/a.kicad_pcb", "Examples/a.kicad_pcb", "hw/test/a.kicad_pcb", "tests_hw/a.kicad_pcb",
                "lib/a.kicad_pcb", "hw/Library/a.kicad_pcb", "hw/a-backup.kicad_pcb", "a/b/demo_board.kicad_pcb"):
        assert not hb.path_ok(bad), bad


def test_repo_filter():
    assert hb.repo_ok("someone/keyboard", False) is None
    assert hb.repo_ok("someone/keyboard", True) == "fork"
    assert hb.repo_ok("KiCad/kicad-demos", False)
    assert hb.repo_ok("someone/kicad-footprints", False)
    assert hb.repo_ok("someone/kicad-tools", False) is None


def test_pick_one_board_per_directory_shallowest_first():
    paths = ["a/b/c/x.kicad_pcb", "main.kicad_pcb", "main2.kicad_pcb", "hw/one.kicad_pcb", "hw/two.kicad_pcb",
             "test/t.kicad_pcb", "z/zz.kicad_pcb"]
    assert hb.pick_paths(paths) == ["main.kicad_pcb", "hw/one.kicad_pcb", "z/zz.kicad_pcb", "a/b/c/x.kicad_pcb"]


def _board(segments, footprints, v5=False):
    fp = "(module Foo (layer F.Cu))" if v5 else '(footprint "Foo" (layer "F.Cu"))'
    return "(kicad_pcb\n" + (fp + "\n") * footprints + "(segment (start 0 0))\n" * segments + \
        "(segments_total 3)\n(fp_segment_like)\n)"


def test_routed_check():
    assert hb.routed_reason(hb.routed_counts(_board(20, 4))) is None
    assert hb.routed_reason(hb.routed_counts(_board(20, 4, v5=True))) is None
    assert "segments" in hb.routed_reason(hb.routed_counts(_board(19, 4)))
    assert "footprints" in hb.routed_reason(hb.routed_counts(_board(50, 3)))
    assert hb.routed_counts(_board(5, 2)) == {"segments": 5, "footprints": 2}


def test_manifest_resumes_and_dedupes(tmp_path):
    path = tmp_path / "harvest.jsonl"
    m = hb.Manifest(path)
    row = {"repo": "a/b", "commit": "c", "path": "x.kicad_pcb", "licence": "MIT", "sha256": "11", "bytes": 5}
    m.add(row)
    assert m.has("a/b", "x.kicad_pcb") and not m.has("a/b", "y.kicad_pcb")
    with path.open("a") as f:
        f.write('{"repo": "cut sh')  # a stopped run left half a line
    again = hb.Manifest(path)
    assert again.count == 1
    assert again.has("a/b", "x.kicad_pcb")
    assert again.duplicate_of("11") == "a/b"
    assert again.duplicate_of("22") is None


def test_parse_response_and_waits():
    status, headers, body = hb.parse_response("HTTP/2.0 403 Forbidden\nRetry-After: 7\nX-Ratelimit-Remaining: 0\n\n{}")
    assert (status, body) == (403, "{}")
    assert hb.wait_for(status, headers, 0) == 8
    assert hb.wait_for(200, {}, 0) == 0
    assert hb.wait_for(429, {}, 1) == 60
    reset = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(__import__("time").time() + 20)}
    assert 15 < hb.wait_for(403, reset, 0) < 25


def test_ranges():
    assert hb.split_range(0, 1000) == ((0, 500), (501, 1000))
    assert hb.split_range(0, 100) is None
    ranges = hb.start_ranges(20000, 1000000)
    assert ranges[0][0] == 20000 and ranges[-1][1] == 1000000
    assert all(a2 == b + 1 for (_, b), (a2, _) in zip(ranges, ranges[1:]))


def _item(repo, path):
    return {"path": path, "repository": {"full_name": repo, "fork": False}}


def test_search_splits_and_resumes(tmp_path, monkeypatch):
    """Ranges over 1000 hits split; a second run asks only for what the first did not settle."""
    calls = []

    def fake(lo, hi, page):
        calls.append((lo, hi, page))
        total = 1500 if hi - lo > 4000 else 3
        return total, [_item("o/r%d_%d_%d" % (lo, hi, page), "b.kicad_pcb")] * (1 if total == 3 else 100)

    monkeypatch.setattr(hb, "search_page", fake)
    monkeypatch.setattr(hb, "start_ranges", lambda lo, hi: [(lo, hi)])
    assert hb.search(tmp_path, 0, 10000, 3) == 3
    rows = [json.loads(x) for x in (tmp_path / "searched.jsonl").read_text().splitlines()]
    assert rows[0]["split"] and rows[0]["total"] == 1500
    first = len(calls)
    assert hb.search(tmp_path, 0, 10000, 3) == 3
    assert len(calls) == first  # enough candidates held: nothing asked again
    assert hb.search(tmp_path, 0, 10000, 4) == 4
    assert calls[first:] == [(7501, 10000, 1)]  # settled and split ranges are not asked again
