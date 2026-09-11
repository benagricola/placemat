#!/usr/bin/env python3
"""One placement pass for a board, as one command, in the foreground.

Why: the pass is always the same sequence, and a session that rebuilds it by
hand loses background jobs and scores boards it never gated. So it is one
tool:

  1. clean board generation: `pcb layout --no-open <board>.zen` into an EMPTY layout dir
     (an incremental run duplicates copper). The generation is cached by a hash of its
     inputs (every .zen under the board dir, modules/ and parts/, every module
     fragment); --fresh forces a regeneration.
  2. the board's layout script (<Name>_layout.py in the board dir)
  3. placemat occupancy --cells   (cross-face + courtyard gate)
  4. kicad-cli pcb drc                  (real buckets + unconnected + outstanding)
  4a. placemat contract           (do the cells' plane drops land?)
  4b. placemat airwires                 (the ratsnest as a number: airwire count, length,
      crossings, per cell; recorded every pass so a placement move shows its effect
      before the trial is spent on it)
  5. --trial: `placemat trial` on the given layers; --quick = the router's main round only
     (a third of the time, about the same closure; iterate on it, record the full one)
  6. a JSON record under --out/<label>/round.json and ONE verdict line;
     --record keeps the full trial record under --out/records as
     routing-<label>-<layers>.json (a work artifact, not a board file)

Exit codes: 0 gates clean; 1 a gate failed (DRC real violations, occupancy hard
conflicts, invalid trial); 2 board generation failed; 3 script failed. Everything runs in
the foreground with a timeout; run from any directory.

Usage:
  placemat round <board>/<board>.zen --label pass1                       # gates + airwires, ~30 s
  placemat round <board>/<board>.zen --label pass1 --trial --quick       # + one-round trial, ~3.5 min
  placemat round <board>/<board>.zen --label pass1 --trial --layers F.Cu B.Cu --record   # full, ~9 min
  placemat round <board.zen> --label x --fresh      # after any .zen or fragment change (the cache notices anyway)
"""
import argparse

from placemat.args import zen as zen_arg
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

sys.dont_write_bytecode = True   # no __pycache__ beside the sources
from placemat.tools.route_trial import run_drc, real_violations, open_by_net, kicad_python  # noqa: E402

def _root():
    """The project's root. Asked for, never computed from this file's own path."""
    from placemat.project import active
    return active().root or os.getcwd()



def _copper_layers(pcb):
    """The copper layers a .kicad_pcb declares, in stack order, read from the
    file - no pcbnew import, this runs in the harness's own interpreter."""
    out = []
    try:
        txt = open(pcb, encoding="utf-8", errors="replace").read(200000)
    except OSError:
        return out
    for m in re.finditer(r'\(\s*\d+\s+"([A-Za-z0-9_.]+)"\s+(?:signal|power|mixed|jumper)\b', txt):
        if m.group(1).endswith(".Cu"):
            out.append(m.group(1))
    return out


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


BUCKET_WORDS = {                       # (one, many) - several do not pluralise with an s
    "via_dangling": ("dangling via", "dangling vias"),
    "track_dangling": ("dangling track", "dangling tracks"),
    "isolated_copper": ("isolated copper island", "isolated copper islands"),
    "clearance": ("clearance violation", "clearance violations"),
    "shorting_items": ("short", "shorts"),
    "track_width": ("narrow track", "narrow tracks"),
    "annular_width": ("thin annulus", "thin annuli"),
    "hole_clearance": ("hole-clearance violation", "hole-clearance violations"),
    "hole_to_hole": ("hole-to-hole violation", "hole-to-hole violations"),
    "courtyards_overlap": ("courtyard overlap", "courtyard overlaps"),
}


def previous_record(out_dir, this_label, pick=None):
    """The pass to compare against: `pick` by label, else the most recent one.

    A number on its own says little - 293 unconnected is only good or bad next
    to what it was last pass - and reading that off two JSON files by hand is
    the most repeated chore in a round."""
    cands = []
    for f in glob.glob(os.path.join(out_dir, "*", "round.json")):
        label = os.path.basename(os.path.dirname(f))
        if label == this_label:
            continue
        if pick and label != pick:
            continue
        try:
            cands.append((os.path.getmtime(f), label, json.load(open(f))))
        except Exception:
            continue
    if not cands:
        return None, None
    _mt, label, rec = max(cands, key=lambda t: t[0])
    return label, rec


def _delta(now, was, better="down"):
    """'12 -> 9 (-3)', with the arrow only when it moved."""
    if was is None or now is None:
        return None
    if now == was:
        return "%s (same)" % now
    sign = "+" if now > was else ""
    return "%s -> %s (%s%s)" % (was, now, sign, now - was)


def compare_passes(rec, old):
    """The handful of numbers a round is actually steering by."""
    out = []
    a, b = rec.get("steps", {}), old.get("steps", {})

    def snap(d, *path):
        for k in path:
            if not isinstance(d, dict):
                return None
            d = d.get(k)
        return d

    for label, now, was in (
        ("unconnected", snap(a, "drc", "unconnected_items"), snap(b, "drc", "unconnected_items")),
        ("occupancy hard", snap(a, "occupancy", "hard"), snap(b, "occupancy", "hard")),
        ("unlanded drops", snap(a, "contract", "unlanded_vias"), snap(b, "contract", "unlanded_vias")),
        ("airwires", snap(a, "airwires", "count"), snap(b, "airwires", "count")),
        ("crossings", snap(a, "airwires", "crossings"), snap(b, "airwires", "crossings")),
    ):
        d = _delta(now, was)
        if d and "same" not in d:
            out.append("%s %s" % (label, d))
    # DRC buckets that appeared or grew
    now_b = dict(snap(a, "drc", "real") or {}, **(snap(a, "drc", "outstanding") or {}))
    was_b = dict(snap(b, "drc", "real") or {}, **(snap(b, "drc", "outstanding") or {}))
    for kind in sorted(set(now_b) | set(was_b)):
        d = _delta(now_b.get(kind, 0), was_b.get(kind, 0))
        if d and "same" not in d:
            one, many = BUCKET_WORDS.get(kind, (kind.replace("_", " "),) * 2)
            out.append("%s %s" % (many, d))
    ca, cb = snap(a, "trial", "closure_clean"), snap(b, "trial", "closure_clean")
    if ca is not None and cb is not None and abs(ca - cb) > 1e-9:
        out.append("closure %.1f%% -> %.1f%% (%+.1f)" % (100 * cb, 100 * ca, 100 * (ca - cb)))
    return out


def say(*parts):
    """Progress and failures. They go to stderr under --format json so stdout
    carries the record and nothing else; a pipe should never have to strip
    chatter out of its input."""
    print(*parts, file=sys.stderr if JSON_OUT[0] else sys.stdout)


JSON_OUT = [False]


def counted(d, empty="clean"):
    """A count-keyed dict as plain words: 'clean', or '39 dangling vias, 2 shorts'.

    Printing the dict itself puts Python's repr in front of a person, which
    reads as debug output beside the rest of the line. Machine-readable output
    is --format json, and the pass record on disk."""
    if not d:
        return empty
    out = []
    for kind, n in sorted(d.items(), key=lambda kv: (-kv[1], kv[0])):
        one, many = BUCKET_WORDS.get(kind, (kind.replace("_", " "),) * 2)
        out.append("%d %s" % (n, one if n == 1 else many))
    return ", ".join(out)


def find_script(board_dir, zen, name):
    cands = sorted(glob.glob(os.path.join(board_dir, "*_layout.py")))
    if name:
        cands = [c for c in cands if os.path.basename(c) == name + "_layout.py"]
    else:
        stem = norm(os.path.splitext(os.path.basename(zen))[0])
        cands = [c for c in cands if norm(os.path.basename(c)[:-len("_layout.py")]) == stem]
    if len(cands) != 1:
        sys.exit("cannot pick the layout script for %s (candidates: %s); pass --name" % (zen, cands))
    return cands[0], os.path.basename(cands[0])[:-len("_layout.py")]


def input_hash(board_dir, zen):
    h = hashlib.sha256()
    files = set(glob.glob(os.path.join(board_dir, "**", "*.zen"), recursive=True))
    files |= set(glob.glob(os.path.join(_root(), "modules", "**", "*.zen"), recursive=True))
    files |= set(glob.glob(os.path.join(_root(), "parts", "**", "*.zen"), recursive=True))
    files |= set(glob.glob(os.path.join(_root(), "modules", "*", "layout", "layout.kicad_pcb")))
    files |= set(glob.glob(os.path.join(_root(), "parts", "**", "*.kicad_mod"), recursive=True))
    for f in sorted(files):
        h.update(f.encode()); h.update(open(f, "rb").read())
    try:
        h.update(subprocess.run(["pcb", "--version"], capture_output=True, text=True).stdout.encode())
    except Exception:
        pass
    return h.hexdigest()[:16]


def sh(cmd, cwd, timeout, log, env=None):
    t = time.time()
    with open(log, "w") as f:
        r = subprocess.run(cmd, cwd=cwd, stdout=f, stderr=subprocess.STDOUT, timeout=timeout, env=env)
    return r.returncode, time.time() - t


def restore_extras(aside, layout_dir):
    """Put back every file the generation did not produce, then drop the copy.

    Names the fresh generation wrote win, so a stale generated file is not
    resurrected; anything else - a hand-saved board, a note, a render someone
    kept - goes back where its owner left it."""
    if not os.path.isdir(aside):
        return []
    kept = []
    for name in sorted(os.listdir(aside)):
        src, dst = os.path.join(aside, name), os.path.join(layout_dir, name)
        if os.path.exists(dst):
            continue
        shutil.move(src, dst)
        kept.append(name)
    shutil.rmtree(aside, ignore_errors=True)
    if kept:
        say("   kept %d file(s) this tool did not generate: %s" % (len(kept), ", ".join(kept)))
    return kept



def parser():
    """The arguments this command takes."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("zen", type=zen_arg, help="board name, or a path to its .zen")
    ap.add_argument("--label", required=True, help="pass name, e.g. pass2c (used in record file names)")
    ap.add_argument("--name", help="board name when the board dir holds several *_layout.py")
    ap.add_argument("--out", help="work root (default <repo>/.rounds/<Name>)")
    ap.add_argument("--fresh", action="store_true", help="regenerate even when the input hash is cached")
    ap.add_argument("--publish", action="store_true",
                    help="promote the built board into the board's layout/ directory. Off by default: "
                         "a pass BUILDS and MEASURES, and the tracked board file is a release, not a "
                         "by-product. Refused when a gate failed.")
    ap.add_argument("--trial", action="store_true", help="run the routing trial after the gates")
    ap.add_argument("--layers", nargs="+", default=["F.Cu", "B.Cu"])
    ap.add_argument("--record", action="store_true", help="keep the full trial record under --out/records")
    ap.add_argument("--render", action="store_true", help="render the board's PNGs this pass (implied by --record; otherwise skipped, they are most of a script's run time)")
    ap.add_argument("--since", metavar="LABEL",
                    help="compare against this pass instead of the most recent one")
    ap.add_argument("--no-compare", action="store_true", help="do not compare with an earlier pass")
    ap.add_argument("--format", choices=("text", "json"), default="text",
                    help="text: the verdict line for a person (default). json: the pass record on stdout")
    ap.add_argument("--quick", action="store_true", help="with --trial: the router's main round only (about a third of the time, about the same closure); a number to iterate on, never recorded")
    ap.add_argument("--iterations", type=int, default=150000)
    return ap


def main(args=None):
    a = args if args is not None else parser().parse_args()
    if a.quick and a.record:
        sys.exit("round.py: --record needs the full trial; drop --quick (or --record)")

    zen = os.path.abspath(a.zen)
    if not os.path.exists(zen):
        sys.exit("no such file: %s" % zen)
    board_dir = os.path.dirname(zen)
    script, name = find_script(board_dir, zen, a.name)
    JSON_OUT[0] = (a.format == "json")
    out = os.path.abspath(a.out or os.path.join(_root(), ".rounds", name))
    run = os.path.join(out, a.label)
    os.makedirs(run, exist_ok=True)
    # THE PASS BUILDS IN ITS OWN DIRECTORY. The tracked board under layout/ is a
    # RELEASE: it is what the last passing pass produced, it is what a person
    # opens and hand-edits, and it is in git. A pass that wrote it directly would
    # mean every experiment - including one that fails its gates, and one that
    # crashes halfway - lands on the file somebody is looking at. So the pass
    # builds here, the gates read here, the renders and any failure screenshot
    # come from here, and only --publish moves it across.
    live_dir = os.path.join(board_dir, "layout", name)
    layout_dir = os.path.join(run, "layout")
    pcb = os.path.join(layout_dir, "layout.kicad_pcb")
    kicad_python()  # fails early if KiCad's python is not configured
    rec = {"board": name, "zen": zen, "label": a.label, "date": time.strftime("%Y-%m-%d %H:%M"), "steps": {}}
    env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}

    # 1. generate the board (cached)
    # A board generation is incremental, so it has to start from an empty
    # directory - but that directory is also where a person opens KiCad and
    # saves, so anything in it that this tool did not generate is theirs and
    # gets put back. The old directory is moved aside rather than deleted, and
    # every name the fresh generation does not produce is restored from it.
    key = input_hash(board_dir, zen)
    cache = os.path.join(out, "gen-cache", key)
    shutil.rmtree(layout_dir, ignore_errors=True)
    os.makedirs(layout_dir, exist_ok=True)
    if a.fresh or not os.path.isdir(cache):
        # `pcb layout` writes to the board's own layout/<name>; generate there
        # into an empty directory, then take the result away and put back
        # whatever the live directory held.
        aside = live_dir + ".aside"
        shutil.rmtree(aside, ignore_errors=True)
        if os.path.isdir(live_dir):
            os.rename(live_dir, aside)
        rc, dt = sh(["pcb", "layout", "--no-open", zen], board_dir, 900, os.path.join(run, "generate.log"), env)
        gen_ok = rc == 0 and os.path.exists(os.path.join(live_dir, "layout.kicad_pcb"))
        if gen_ok:
            shutil.rmtree(layout_dir, ignore_errors=True)
            shutil.move(live_dir, layout_dir)
        else:
            shutil.rmtree(live_dir, ignore_errors=True)
        if os.path.isdir(aside):
            os.rename(aside, live_dir)        # the tracked board is untouched by a pass
        rc = 0 if gen_ok else (rc or 1)
        if rc != 0 or not os.path.exists(pcb):
            say("round %s: BOARD GENERATION FAILED (%s)" % (a.label, os.path.join(run, "generate.log")))
            return 2
        shutil.rmtree(cache, ignore_errors=True)
        shutil.copytree(layout_dir, cache)
        rec["steps"]["generate"] = {"seconds": round(dt, 1), "cached": False, "hash": key}
    else:
        shutil.rmtree(layout_dir, ignore_errors=True)
        shutil.copytree(cache, layout_dir)
        rec["steps"]["generate"] = {"seconds": 0, "cached": True, "hash": key}

    # 2. script (renders only when the pass will be looked at or kept)
    senv = dict(os.environ)
    senv["LAYOUT_RENDER"] = "1" if (a.render or a.record) else "0"
    # A STAGED SCRIPT DOES NOTHING AT IMPORT - its bodies only register - so it
    # is run through the runner, which owns the environment and the stage order.
    # An unmigrated script still runs itself, unchanged.
    staged = "layout_stage" in open(script).read()
    # the layout runner is part of placemat, so it is invoked as one - never by
    # a path into the project, which is where it used to live
    cmd = ([sys.executable, "-m", "placemat.tools.layout", board_dir, "--board-file", pcb]
           if staged else [sys.executable, script, pcb])
    rc, dt = sh(cmd, board_dir, 900, os.path.join(run, "script.log"), senv)
    rec["steps"]["script"] = {"seconds": round(dt, 1), "rc": rc}
    if rc != 0:
        say("round %s: SCRIPT FAILED rc=%d, tail of %s:" % (a.label, rc, os.path.join(run, "script.log")))
        say("".join(open(os.path.join(run, "script.log")).readlines()[-15:]))
        return 3
    # 2a. does the script match the current standard? Reported every pass, so a
    #     script that predates a library primitive is visible before someone
    #     edits around it - which is how a set of scripts becomes a mixture.
    try:
        from placemat.tools.layout_lint import lint as _lint, library_api as _library_api
        legacy = _lint(script, _library_api(_root()))
    except Exception as e:                      # a lint failure never blocks a pass
        legacy = None
        say("lint unavailable: %s" % e)
    if legacy is not None:
        # A local helper is a QUESTION (is this the library's job, under another
        # name?), not a defect - the migration rule answers it by proposing.
        # The mechanical idioms are the ones with a library call waiting.
        helpers = [f for f in legacy if f["rule"] == "local_def"]
        legacy = [f for f in legacy if f["rule"] != "local_def"]
        if legacy or helpers:
            rec["steps"]["script"]["legacy"] = {"findings": len(legacy),
                                                "kinds": sorted({f["rule"] for f in legacy}),
                                                "local_helpers": len(helpers)}

    notes = [l.rstrip() for l in open(os.path.join(run, "script.log"))
             if re.search(r"place_free:|compaction|settle|purged|NO FIT|unsettled|clash", l)]

    # 3. occupancy
    occ_log = os.path.join(run, "occupancy.txt")
    rc, dt = sh([sys.executable, os.path.join(_root(), "tools", "board_occupancy.py"), pcb, "--cells"], _root(), 600, occ_log)
    occ = open(occ_log).read()
    hard = sum(int(m) for m in re.findall(r"\bhard\s+(\d+)", occ))
    rec["steps"]["occupancy"] = {"seconds": round(dt, 1), "hard": hard, "rc": rc}

    # 4. DRC
    drc = run_drc(pcb, os.path.join(run, "drc.json"))
    real = real_violations(drc)
    unconnected = sum(open_by_net(drc).values())
    def _bucket(kind):
        return sum(1 for v in drc.get("violations", []) if v["type"] == kind)
    # Dangling and isolated copper are NOT accepted at board level: on a
    # fragment they mean "no board yet", on a board they mean the plane or the
    # trace that should pick this up has not been drawn. They are reported as
    # outstanding rather than folded into `real`, which is the clearance-class
    # set, and the contract gate above attributes them to a cell and a net.
    outstanding = {k: _bucket(k) for k in ("via_dangling", "track_dangling", "isolated_copper")
                   if _bucket(k)}
    rec["steps"]["drc"] = {"real": real, "unconnected_items": unconnected,
                           "outstanding": outstanding,
                           "courtyards_overlap": _bucket("courtyards_overlap")}

    # 4a. stamp contract: does the board provide what its cells assume? A
    #     plane drop that lands in nothing is the board's defect, not the
    #     cell's, and only shows up once the cell is on a board.
    con_log = os.path.join(run, "contract.txt")
    con_json = os.path.join(run, "contract.json")
    rc, dt = sh([kicad_python(), os.path.join(_root(), "tools", "stamp_contract.py"), pcb, "--json", con_json],
                _root(), 600, con_log)
    contract = None
    if os.path.exists(con_json):
        contract = json.load(open(con_json))[0]
        rec["steps"]["contract"] = {"seconds": round(dt, 1),
                                    "unlanded_vias": contract["unlanded_vias"],
                                    "cells_affected": contract["cells_affected"],
                                    "empty_copper_layers": contract["empty_copper_layers"]}
        for line in open(con_log):
            if "UNLANDED" in line or "EMPTY LAYER" in line:
                notes.append(line.strip())
    else:
        rec["steps"]["contract"] = {"seconds": round(dt, 1), "rc": rc, "failed": True}

    # 4a2. link classes: did the connections that must be short end up short?
    #      Reported when the script declared any; a link with a declared limit
    #      that missed it fails the pass, because a class nobody checks is
    #      decoration.
    links = None
    lf = os.path.join(layout_dir, "links-achieved.json")
    if os.path.exists(lf):
        try:
            links = json.load(open(lf))
        except Exception:
            links = None
    if links:
        # the heaviest tier is the one the placement was told to buy, so that is
        # what the pass reports; the weight is whatever the script asked for, a
        # named class or a number
        top_w = max((r["weight"] for r in links), default=0.0)
        top = [r for r in links if r["weight"] == top_w]
        over = [r for r in links if r.get("over_limit")]
        rec["steps"]["links"] = {"declared": len(links), "top_weight": top_w,
                                 "top_name": top[0].get("name") if top else None,
                                 "at_top_weight": len(top),
                                 "over_limit": [{"a": r["a"], "b": r["b"], "mm": r["mm"],
                                                 "limit_mm": r["limit_mm"]} for r in over],
                                 "worst_at_top_mm": max([r["mm"] for r in top], default=None)}
        for r in over:
            notes.append("LINK OVER LIMIT %s <-> %s  %.2f mm (limit %.2f) %s"
                         % (r["a"], r["b"], r["mm"], r["limit_mm"], r["why"][:40]))

    # 4b. airwires (the ratsnest measure, from the geometry oracle)
    aw = None
    aw_json = os.path.join(run, "airwires.json")
    rc, dt = sh([kicad_python(), os.path.join(_root(), "tools", "airwires.py"), pcb, "--json", aw_json, "--top", "6"],
                _root(), 600, os.path.join(run, "airwires.log"))
    if rc == 0 and os.path.exists(aw_json):
        aw = json.load(open(aw_json))
        cells = sorted(aw["per_owner"].items(), key=lambda kv: -kv[1]["external_mm"])[:6]
        rec["steps"]["airwires"] = {"seconds": round(dt, 1), "count": aw["count"], "total_mm": aw["total_mm"],
                                    "crossings": aw["crossings"],
                                    "top_cells": {k: v["external_mm"] for k, v in cells}}
    else:
        rec["steps"]["airwires"] = {"seconds": round(dt, 1), "rc": rc, "failed": True}

    # 5. trial
    trial = None
    if a.trial:
        tdir = os.path.join(run, "trial")
        shutil.rmtree(tdir, ignore_errors=True)
        targs = ["--iterations", str(a.iterations), "--out", tdir] + (["--quick"] if a.quick else []) + (["--render"] if (a.render or a.record) else [])
        rc, dt = sh([sys.executable, os.path.join(_root(), "tools", "route_trial.py"), pcb, "--layers"] + a.layers + targs,
                    _root(), 3600, os.path.join(run, "trial.log"))
        recs = glob.glob(os.path.join(tdir, "*.route_trial.json"))
        if rc == 0 and recs:
            trial = json.load(open(recs[0]))
            rec["steps"]["trial"] = {"seconds": round(dt, 1), "quick": bool(a.quick), "closure": trial["closure"], "closure_clean": trial["closure_clean"],
                                     "valid": trial["valid"], "open_items": trial["after"]["signal_open_items"],
                                     "open_nets": trial["after"]["signal_open_nets"],
                                     "why_open": trial.get("why_open_counts", {}), "record": recs[0]}
            if a.record:
                abbrev = "".join("I" if l.startswith("In") else l[0] for l in a.layers)
                keep = os.path.join(out, "records")
                os.makedirs(keep, exist_ok=True)
                dst = os.path.join(keep, "routing-%s-%s.json" % (a.label, abbrev))
                shutil.copy(recs[0], dst)
                rec["steps"]["trial"]["kept_record"] = dst
        # The routed board is a MEASUREMENT, never design copper - but it is
        # the only picture of what the routing actually looks like, and it was
        # only ever written into the run directory where nobody goes. Copy it
        # beside the board under a name that cannot be mistaken for the design,
        # with the house render colours so it reads like the other renders.
        if rc == 0:
            routed = glob.glob(os.path.join(tdir, "*.routed.kicad_pcb"))
            if routed:
                pv = os.path.join(layout_dir, "routed-preview.kicad_pcb")
                shutil.copy(routed[0], pv)
                for ext in (".kicad_pro", ".kicad_dru"):
                    src = routed[0].replace(".kicad_pcb", ext)
                    if os.path.exists(src):
                        shutil.copy(src, pv.replace(".kicad_pcb", ext))
                try:
                    from placemat.layout_helpers import patch_stackup_colors
                    patch_stackup_colors(pv)
                except Exception:
                    pass
                # FLAT COPPER PLOTS, not the 3D render. A raytraced render puts
                # the traces under soldermask, where 2400 of them are all but
                # invisible; the thing to look at when reviewing routing is the
                # layer as the fab sees it.
                made = []
                # every copper layer the board declares, not only the ones the
                # router was given: the inner layers carry the board's own
                # planes and rails, and a picture that leaves them out is a
                # picture of a different board.
                _plot_layers = list(dict.fromkeys(list(a.layers) + _copper_layers(pv)))
                for lay in _plot_layers:
                    svg = os.path.join(tdir, "plot-%s.svg" % lay.replace(".", "_"))
                    png = os.path.join(layout_dir, "routed-preview-%s.png"
                                       % lay.replace(".", "_"))
                    rc2 = subprocess.run(["kicad-cli", "pcb", "export", "svg",
                                          "--layers", "%s,Edge.Cuts" % lay,
                                          "--mode-single", "--fit-page-to-board",
                                          "--exclude-drawing-sheet", "--check-zones",
                                          "-o", svg, pv],
                                         stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL).returncode
                    if rc2 == 0 and os.path.exists(svg):
                        if subprocess.run(["rsvg-convert", "-w", "1400", "-b", "white",
                                           svg, "-o", png],
                                          stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL).returncode == 0:
                            made.append(os.path.basename(png))
                rec["steps"]["trial"]["preview"] = pv
                notes.append("routed preview: %s%s"
                             % (pv, (" + " + ", ".join(made)) if made else
                                "  (no copper plot: kicad-cli export svg or rsvg-convert failed)"))
        else:
            rec["steps"]["trial"] = {"seconds": round(dt, 1), "rc": rc, "failed": True}

    prev_label, prev = (None, None) if a.no_compare else previous_record(out, a.label, a.since)
    changes = compare_passes(rec, prev) if prev else []
    if prev_label:
        rec["compared_with"] = {"label": prev_label, "changes": changes}

    json.dump(rec, open(os.path.join(run, "round.json"), "w"), indent=1)

    # 6. verdict
    links_ok = not links or not any(r.get("over_limit") for r in links)
    contract_ok = contract is None or (not contract["unlanded_vias"]
                                       and not contract["empty_copper_layers"])
    gate_ok = not real and hard == 0 and contract_ok and links_ok and (trial is None or trial["valid"])
    bits = ["round %s (%s): board %s" % (a.label, name, "cached" if rec["steps"]["generate"]["cached"] else "fresh %.0fs" % rec["steps"]["generate"]["seconds"]),
            "script ok %.0fs%s" % (rec["steps"]["script"]["seconds"],
                                   "" if not legacy else
                                   " (%d legacy idiom(s): %s - migrate first, `placemat lint`)"
                                   % (len(legacy), ", ".join(sorted({f["rule"] for f in legacy})[:4]))),
            "occupancy hard %d" % hard,
            "DRC %s, unconnected %d%s" % (counted(real), unconnected,
                                          (", outstanding " + counted(outstanding)) if outstanding else "")]
    if links:
        top_w = max((r["weight"] for r in links), default=0.0)
        top = [r for r in links if r["weight"] == top_w]
        over = sum(1 for r in links if r.get("over_limit"))
        bits.append("links %d (%d %s, worst %.1f mm%s)"
                    % (len(links), len(top), top[0].get("name") or "at weight %g" % top_w,
                       max([r["mm"] for r in top], default=0.0),
                       ", %d OVER LIMIT" % over if over else ""))
    if contract is not None:
        bits.append("contract %s" % (
            "ok" if contract_ok else
            "%d unlanded drop(s) in %d cell(s)%s" % (
                contract["unlanded_vias"], contract["cells_affected"],
                (", empty " + "+".join(contract["empty_copper_layers"]))
                if contract["empty_copper_layers"] else "")))
    if aw is not None:
        bits.append("airwires %d, %.0f mm, %d crossings" % (aw["count"], aw["total_mm"], aw["crossings"]))
    if trial is not None:
        # CLEAN only. A route that reaches its pad through a short or a
        # clearance violation has not routed the net, so the raw figure is not a
        # result - it is the clean one plus whatever the router got away with.
        # It stays in the JSON record for forensics and out of the verdict line.
        # WHY the open nets are open: a terminal nothing can reach is not the
        # same finding as a net that searched and lost, and only the second is
        # worth another placement pass.
        why = trial.get("why_open_counts", {})
        short = {"terminal_blocked": "boxed at a terminal", "blocked_by_copper": "blocked by copper",
                 "multipoint_edge_failed": "multi-pad net short of pads",
                 "unclassified": "no verdict", "not_attempted": "not attempted"}
        why_txt = ", ".join("%d %s" % (n, short.get(k, k))
                            for k, n in sorted(why.items(), key=lambda kv: -kv[1]))
        bits.append("trial%s %s closure %.1f%% (%d open on %d nets%s)%s"
                    % (" QUICK" if a.quick else "", "+".join(a.layers), 100 * trial["closure_clean"],
                       trial["after"]["signal_open_items"], trial["after"]["signal_open_nets"],
                       ("; " + why_txt) if why_txt else "",
                       "" if trial["valid"] else " INVALID"))
    elif a.trial:
        bits.append("trial FAILED (see %s)" % os.path.join(run, "trial.log"))
    if a.format == "json":
        rec["gate_ok"] = gate_ok
        rec["notes"] = notes
        json.dump(rec, sys.stdout, indent=1)
        sys.stdout.write("\n")
    else:
        print(" | ".join(bits))
        if prev_label:
            print("   vs %s: %s" % (prev_label, ", ".join(changes) if changes
                                    else "nothing moved"))
        for n in notes[:12]:
            print("   " + n)
        print("   record %s" % os.path.join(run, "round.json"))
    # PUBLISH, and only on request. The tracked board is a release: it is what a
    # person opens, hand-edits and commits, and what the next fold-in diffs
    # against. A pass that promoted its own output would make every experiment a
    # release, including the ones that fail - so the gates decide, and they
    # decide BEFORE the copy rather than after it.
    if a.publish:
        if not gate_ok:
            say("   NOT PUBLISHED: a gate failed. The build is at %s" % layout_dir)
            return 1
        extras = restore_extras(live_dir, layout_dir)   # whatever a person saved there
        shutil.rmtree(live_dir + ".old", ignore_errors=True)
        if os.path.isdir(live_dir):
            os.rename(live_dir, live_dir + ".old")
        shutil.copytree(layout_dir, live_dir)
        shutil.rmtree(live_dir + ".old", ignore_errors=True)
        say("   published -> %s%s" % (live_dir, " (kept %d file(s) of yours)" % len(extras) if extras else ""))
    return 0 if gate_ok else 1


if __name__ == "__main__":
    sys.exit(main())
