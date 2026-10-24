"""Turn human-routed KiCad boards into training records (kicad/training.py): the placed board is the board with its
tracks, vias and copper zones removed, the route is the human's.

    python tools/reference_training.py OUT [BOARD.kicad_pcb ...] [--reference] [--kicad-demos [DIR]] [--cell-mm MM] [--facts FILE]

Each board gets OUT/<name>/route/ holding placed.kicad_pcb, training.json and training.raster, so that
`tools/training_collect.py DATASET OUT` finds it. A board that does not load, has no footprints or has no tracks is
skipped, and the skip is printed with its reason.

--facts FILE is a JSON object keyed by board path as given on the command line. Its values are facts added to that
board's record (for example repo, commit, path and licence); a "name" in it names the record folder and the board.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "fixtures/reference"))


class Skip(Exception):
    """A board that gives no record; the message says why."""


def kicad_demos_dir() -> Path | None:
    """KiCad's demo folder in the share folder of the install that holds kicad-cli, or None."""
    cli = shutil.which("kicad-cli")
    if cli:
        found = Path(cli).resolve().parent.parent / "share/kicad/demos"
        if found.is_dir():
            return found
    return None


def open_counts(board, pcbnew) -> dict:
    """{net: open connections} of a loaded, joined board: its islands holding a pad, minus 1."""
    from placemat.kicad.airwires import item_islands
    return {net: len(islands) - 1 for net, islands in item_islands(board, pcbnew).items()}


def make_placed(board, pcbnew) -> dict:
    """Remove every track, via and copper zone (not rule areas) from a loaded board; {"tracks", "zones"} removed."""
    gone = {"tracks": 0, "zones": 0}
    items = [("tracks", t) for t in list(board.GetTracks())]
    items += [("zones", z) for z in list(board.Zones()) if not z.GetIsRuleArea()]
    for kind, item in items:
        group = item.GetParentGroup()
        if group is not None:
            group.RemoveItem(item)
        board.Delete(item)
        gone[kind] += 1
    return gone


def make_record(pcb: Path, out: Path, name: str, origin: str, cell_mm: float, extra: dict | None = None) -> dict:
    """Write OUT/route/ for a human-routed board and return the summary row; Skip when it gives no record."""
    from placemat.kicad.airwires import load_joined
    from placemat.kicad.quiet import import_pcbnew, quiet_stderr
    from placemat.kicad.training import TRAINING_JSON, write_record
    started = time.monotonic()
    pcbnew = import_pcbnew()
    try:
        with quiet_stderr():
            board = pcbnew.LoadBoard(str(pcb))
    except Exception as e:
        raise Skip("does not load: %s" % str(e).strip().splitlines()[0] if str(e).strip() else "does not load")
    if board is None:
        raise Skip("does not load")
    if not list(board.GetFootprints()):
        raise Skip("no footprints")
    if not list(board.GetTracks()):
        raise Skip("not routed (no tracks)")
    work = out / "route"
    work.mkdir(parents=True, exist_ok=True)
    placed = work / "placed.kicad_pcb"
    removed = make_placed(board, pcbnew)
    board.Save(str(placed))
    _, board_before = load_joined(placed)
    open_before = open_counts(board_before, pcbnew)
    _, board_after = load_joined(pcb)
    open_after = open_counts(board_after, pcbnew)
    total = sum(open_before.values())
    closure = (total - sum(min(open_after.get(n, 0), v) for n, v in open_before.items())) / total if total else 1.0
    facts = dict(extra or {}, source="human", board=name, origin=origin, closure=round(closure, 4))
    path = write_record(placed, pcb, work, open_before, open_after, facts, cell_mm)
    record = json.loads(path.read_text())
    return {"board": name, "nets": len(record["nets"]), "open_before": total, "open_after": sum(open_after.values()),
            "closure": closure, "tracks_removed": removed["tracks"], "zones_removed": removed["zones"],
            "size": record["width"] * record["height"], "bytes": (work / record["raster"]).stat().st_size,
            "seconds": round(time.monotonic() - started, 1)}


def reference_boards() -> list:
    """[(pcb, name, origin)] of the reference set's boards, from the cache."""
    import fetch
    out = []
    for b in fetch.load_manifest():
        folder = fetch.fetch(b, offline=True)
        out.append((folder / b.board, b.name, "%s@%s" % (b.repo, b.commit)))
    return out


def demo_boards(folder: Path) -> list:
    out = []
    for pcb in sorted(folder.rglob("*.kicad_pcb")):
        out.append((pcb, pcb.stem, "kicad-demo:%s" % pcb.stem))
    return out


def main(argv=None) -> int:
    from placemat.settings import Settings
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("out", type=Path)
    ap.add_argument("boards", nargs="*", type=Path)
    ap.add_argument("--reference", action="store_true", help="the boards of fixtures/reference/manifest.json, from the cache")
    ap.add_argument("--kicad-demos", nargs="?", const="", metavar="DIR", help="every board under KiCad's demo folder, or DIR")
    ap.add_argument("--facts", type=Path, help="JSON {board path: facts to add to its record}")
    ap.add_argument("--cell-mm", type=float, default=Settings().route_training_cell_mm)
    args = ap.parse_args(argv)
    todo = [(p, p.stem, "file:%s" % p.name) for p in args.boards]
    if args.reference:
        todo += reference_boards()
    if args.kicad_demos is not None:
        demos = Path(args.kicad_demos) if args.kicad_demos else kicad_demos_dir()
        if demos is None:
            print("KiCad's demos not found beside kicad-cli; name the folder with --kicad-demos DIR", file=sys.stderr)
            return 2
        todo += demo_boards(demos)
    if not todo:
        ap.error("no boards given")
    extras = json.loads(args.facts.read_text()) if args.facts else {}
    rows, seen = [], set()
    for pcb, name, origin in todo:
        extra = dict(extras.get(str(pcb), {}))
        name = extra.pop("name", name)
        if "repo" in extra and "commit" in extra:
            origin = "%s@%s" % (extra["repo"], extra["commit"])
        if name in seen:
            name = "%s-%s" % (pcb.parent.name, name)
        seen.add(name)
        try:
            row = make_record(pcb, args.out / name, name, origin, args.cell_mm, extra)
        except Skip as e:
            print("skipped %s: %s" % (name, e))
            continue
        rows.append(row)
        print(json.dumps(row, sort_keys=True), flush=True)
    print("%d record(s), %d skipped" % (len(rows), len(todo) - len(rows)))
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())
