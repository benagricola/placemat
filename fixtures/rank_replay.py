"""Which run each ranking keeps: the recorded runs of a board, walked in the
order they were made, the best of each family kept as best.json keeps it -
once by the fixed order of 0.32 (placed, DRC, findings, airwire) and once by
the run score at the given weights. Runs recorded before the score have no
measures, so they are rebuilt from what each run kept:

- unplaced parts: the steps whose note says UNPLACED, by the step's priority;
- DRC: the run's real violations;
- links past their limit: the findings' own numbers, each weighed by the
  link as the script declares it now;
- the other findings: by their wording, into the kinds of findings.py;
- crossings: the run's drc.json read again, the script's planes and free
  nets set apart;
- airwire: the run's.

    .venv/bin/python fixtures/rank_replay.py BOARD_DIR [--set score.crossing=3 ...]

BOARD_DIR holds the scripts (*_layout.py) and .placemat/runs.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import re
import sys

_LINK = re.compile(r"^link (\S+?)\.(\S+) to (\S+?)\.(\S+) is ([\d.]+) mm, over its ([\d.]+) mm limit")
_UNPLACED_WORDS = ("no room anywhere", "no legal spot within", "no pocket fits")


def kind_of(text: str) -> str | None:
    """A 0.32 finding's kind, by its wording; None for what the score counts apart."""
    if text.startswith("worse than the best run") or _LINK.match(text) or any(w in text for w in _UNPLACED_WORDS):
        return None
    if " sits on " in text:
        return "label"
    if text.startswith(("copper ", "track ", "via ")) or " cross on " in text or "crosses FIXED" in text \
            or "crosses keepout" in text:
        return "copper"
    if "no declaration places it" in text or " declares " in text or text.startswith("web "):
        return "setup"
    if re.search(r"\((fixed|cutout|keepout|edge|decided)\):", text):
        return "fixed"
    return "setup"


def script_facts(script: pathlib.Path):
    """(link weights by pad pair, quiet nets) as the script declares them now."""
    from placemat import settings as settings_mod
    from placemat.project import fab_profile, find_board
    from placemat.runner import cached_generation, scripted_board
    src = find_board(script)
    cfg = settings_mod.load(src.board_dir)
    with settings_mod.bind(cfg):
        fab = fab_profile(src.board_dir)
        generated = cached_generation(src) / src.pcb.name
        board = scripted_board(script, src, cfg, fab, keep_going=True, pcb=generated if generated.exists() else None)
    weights = {}
    for l in board._links:
        weights[(tuple(l.a), tuple(l.b))] = weights[(tuple(l.b), tuple(l.a))] = int(l.weight)
    return weights, set(board._plane_nets()) | set(board._free_nets)


def measures_of(run_dir: pathlib.Path, rec, weights: dict, quiet: set) -> dict:
    from placemat.report import _drc_total, airwires_from_drc
    unplaced: dict = {}
    for s in rec.steps:
        if s.get("kind") in ("part", "cell", "block") and "UNPLACED" in (s.get("note") or ""):
            p = s.get("priority") or "default"
            unplaced[p] = unplaced.get(p, 0) + 1
    excess, found = 0.0, {}
    for f in rec.findings:
        m = _LINK.match(f)
        if m:
            a, b = (m.group(1), m.group(2)), (m.group(3), m.group(4))
            excess += (float(m.group(5)) - float(m.group(6))) * weights.get((a, b), 1)
            continue
        k = kind_of(f)
        if k is not None:
            found[k] = found.get(k, 0) + 1
    aw = airwires_from_drc(json.loads((run_dir / "drc.json").read_text()), quiet)
    return {"unplaced": unplaced, "drc": _drc_total(rec.metrics), "link_excess": round(excess, 6), "findings": found,
            "crossings": {"signal": aw["crossings"] - aw["crossings_quiet"], "plane": aw["crossings_quiet"]},
            "airwire_mm": rec.metrics.get("airwire_mm") or 0.0}


def _old_better(a, b) -> bool:
    """0.32's rule: placed, DRC, findings, then airwire beyond 1%."""
    from placemat.report import _drc_total
    ka = (-int(a.metrics.get("placed") or 0), _drc_total(a.metrics), int(a.metrics.get("findings") or 0))
    kb = (-int(b.metrics.get("placed") or 0), _drc_total(b.metrics), int(b.metrics.get("findings") or 0))
    if ka != kb:
        return ka < kb
    x, y = float(a.metrics.get("airwire_mm") or 0), float(b.metrics.get("airwire_mm") or 0)
    return abs(x - y) > 0.01 * max(x, y) and x < y


def main(argv) -> int:
    from placemat import score
    from placemat.report import RunRecord, family_of
    from placemat.settings import Settings, split_key
    ap = argparse.ArgumentParser()
    ap.add_argument("board_dir")
    ap.add_argument("--set", action="append", default=[], help="section.key=value, e.g. score.crossing=3")
    args = ap.parse_args(argv)
    cfg = Settings()
    for item in args.set:
        key, _, value = item.partition("=")
        name = key.replace(".", "_", 1)
        cfg = dataclasses.replace(cfg, **{name: type(getattr(cfg, name))(value)})
    root = pathlib.Path(args.board_dir).resolve()
    facts = {}
    families: dict = {}
    for run_json in sorted((root / ".placemat" / "runs").glob("*/run.json"), key=lambda p: p.stat().st_mtime):
        try:
            rec = RunRecord.load(run_json)
        except (json.JSONDecodeError, OSError):
            continue
        if rec.status != "ok" or "drc_real" not in rec.metrics or not (run_json.parent / "drc.json").exists():
            continue
        script = root / ("%s_layout.py" % rec.board)
        if not script.exists():
            continue
        if script not in facts:
            facts[script] = script_facts(script)
        weights, quiet = facts[script]
        m = measures_of(run_json.parent, rec, weights, quiet)
        families.setdefault((rec.board, family_of(rec)), []).append((rec, m))
    changed = 0
    for (board, fam), runs in sorted(families.items(), key=lambda kv: (kv[0][0], -len(kv[1]))):
        if len(runs) < 2:
            continue
        old = new = None
        for rec, m in runs:
            if old is None or _old_better(rec, old[0]):
                old = (rec, m)
            if new is None or score.compare(m, new[1], cfg)[0] < 0:
                new = (rec, m)
        same = old[0].run_id == new[0].run_id
        changed += not same
        print("%-10s family %s: %d runs; kept by 0.32's order %s, by the score %s%s" % (
            board, fam[:8], len(runs), old[0].run_id, new[0].run_id, "" if same else "  <- differs"))
        if not same:
            to, tn = score.terms(old[1], cfg), score.terms(new[1], cfg)
            print("    score: %s %.1f mm, %s %.1f mm" % (old[0].run_id, sum(to.values()), new[0].run_id, sum(tn.values())))
            for t in score.TERMS:
                if abs(to[t] - tn[t]) > 1e-6:
                    print("      %-15s %10.1f %10.1f" % (t, to[t], tn[t]))
            for label, (rec, m) in (("0.32", old), ("score", new)):
                print("    %-5s %s: placed %s, DRC %d, findings %d, airwire %.1f, crossings %d signal + %d plane, "
                      "link excess %.2f" % (label, rec.run_id, rec.metrics.get("placed"), m["drc"],
                                            rec.metrics.get("findings") or 0, m["airwire_mm"],
                                            m["crossings"]["signal"], m["crossings"]["plane"], m["link_excess"]))
    print("%d famil%s kept a different run" % (changed, "y" if changed == 1 else "ies"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
