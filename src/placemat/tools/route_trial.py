#!/usr/bin/env python3
"""Routability gate: how much of a placed board a strict, bounded autorouter can close.

Why: placement was tuned for weeks on this project without a routing pass to
test it. This tool makes routability a number that every placement round can
be scored by, and makes the number comparable between rounds by pinning the
router, its flags and the layer set.

What it does, in order:
  1. copies the board (and its .kicad_pro / .kicad_dru) into a work dir
  2. LOCKS every existing track, via and copper polygon (the router never rips
     KiCad-locked copper; unlocked, it reworks excluded power nets and trims
     pour-connected cell copper)
  3. runs kicad-cli DRC before, and splits the open connections into SIGNAL
     (routed here) and PLANE nets (ground, rails, phases: excluded by net class,
     they are plane and pour work)
  4. runs KiCadRoutingTools on the signal nets only, on the given layers, with
     rule escalation OFF (its default shrinks tracks to the fab floor to get
     through, which breaks the board's own rules) and a bounded iteration
     budget (an unbounded run exhausts memory)
  5. runs kicad-cli DRC after: closure, remaining open nets, and every
     violation bucket (the router can drive a signal through a ground polygon;
     DRC, not the router's summary, is the truth)
  6. attributes every net still open to the cells its pads belong to
     (hierarchical Path): module-internal, board-level, or cross-face
  7. writes <work>/<board>.route_trial.json and prints a summary table;
     --render writes top/bottom PNGs; --film makes the trace-replay GIF from a
     SEPARATE traced run so a film can never touch a score

The metric is CLOSURE: the share of open signal connections closed under the
real rules on the declared layers. Two numbers are reported: the raw closure
and the CLEAN closure, which counts a signal net the router drove through a
short or a clearance violation as still fully open (the router is
pour-blind). Use the clean number for acceptance. A record is marked INVALID
when the placement's own DRC before routing has clearance, shorting or hole
violations: a score on a shorted placement means nothing. It is a proxy for
hand routability, not a proof: a board the router closes to the mid-nineties
is one a person finishes; the last few nets are always hand work. The router
is deterministic on an identical FILE but sensitive to item order: a board
regenerated from the same script scores a point or two differently from the
committed copy of the same geometry. So compare only runs made the same way
(baseline and rounds both on a fresh clean regeneration), with identical router
version, flags and layer set (all recorded in the JSON).

Only one trial runs at a time per machine: a second invocation queues on a
lock file in the router checkout (two routers at once starve the machine);
--no-wait exits instead.

Usage:
  placemat trial <board>/layout/<Board>/layout.kicad_pcb
  placemat trial <board.kicad_pcb> --layers F.Cu In2.Cu B.Cu --render --film
  placemat trial <board.kicad_pcb> --exclude-classes GND_RET HV_BUS LOGIC_PWR HV_TRUNK
  placemat trial --rescore <work dir>     # add clean closure + validity to an old record

Needs: KiCadRoutingTools at --router (default ~/work/KiCadRoutingTools, with
its .venv) and kicad-cli on PATH. It runs under placemat's own interpreter;
KICAD_PYTHON_INTERPRETER overrides that on a machine with several KiCads.
"""
import argparse
import collections
import fcntl
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import time

ROUTER_DEFAULT = os.path.expanduser("~/work/KiCadRoutingTools")
PINNED_ROUTER = "0.22.0"
DEFAULT_EXCLUDED_CLASSES = ("GND_RET", "HV_BUS", "LOGIC_PWR", "HV_TRUNK")


# ----------------------------------------------------------------- environment
def kicad_python():
    """The interpreter to run the router under.

    placemat's own carries pcbnew, so that is the answer unless a machine with
    several KiCads names another."""
    p = os.environ.get("KICAD_PYTHON_INTERPRETER")
    return p if p and os.path.exists(p) else sys.executable


def router_version(router_dir):
    try:
        return open(os.path.join(router_dir, "VERSION")).read().strip()
    except OSError:
        return "unknown"


# ---------------------------------------------------------------- net classes
def netclass_map(pro_path):
    """net name -> class name, from the .kicad_pro patterns and explicit
    assignments (fnmatch semantics as KiCad applies them; first match wins,
    explicit assignment beats a pattern)."""
    if not pro_path or not os.path.exists(pro_path):
        return {}, []
    d = json.load(open(pro_path))
    ns = d.get("net_settings", {})
    patterns = [(p.get("pattern"), p.get("netclass")) for p in ns.get("netclass_patterns", [])]
    explicit = ns.get("netclass_assignments", {}) or {}
    return explicit, patterns


def class_of(net, explicit, patterns):
    if net in explicit:
        v = explicit[net]
        return v[0] if isinstance(v, list) and v else v
    for pat, cls in patterns:
        if pat and fnmatch.fnmatchcase(net, pat):
            return cls
    return "Default"


# ------------------------------------------------------------------------ DRC
def run_drc(pcb, out_json):
    """DRC with the zones REFILLED first.

    A zone reflows around whatever copper is added to a board, so a router is
    right to route across one - but only once someone refills it. `kicad-cli
    pcb drc` refills only when asked, so without this flag a routed board is
    graded against the STALE fill and every trace laid across a zone reads as
    a short. That is the mirror of the pour bug: there the router was wrong
    about static copper, here the grader would be wrong about dynamic copper.

    The refill is for the DRC only (no --save-board): the board file keeps the
    fill it came with, and a measurement never edits the design."""
    subprocess.run(["kicad-cli", "pcb", "drc", "--refill-zones",
                    "--format", "json", "--output", out_json, pcb],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=os.path.dirname(pcb))
    return json.load(open(out_json))


def open_by_net(drc):
    c = collections.Counter()
    for x in drc.get("unconnected_items", []):
        for i in x.get("items", []):
            m = re.search(r"\[([^\]]+)\]", i.get("description", ""))
            if m:
                c[m.group(1)] += 1
                break
    return c


def buckets(drc):
    return dict(collections.Counter(v["type"] for v in drc.get("violations", [])))


REAL_KINDS = ("clearance", "shorting_items", "track_width", "annular_width", "hole_clearance", "hole_to_hole")


def real_violations(drc):
    return {k: v for k, v in buckets(drc).items() if k in REAL_KINDS}


# WHY a net is still open. The router decides this itself and exports the
# decision: `boxed_in` carries a per-net verdict with the geometry it was
# routing at, and `blockers` names the copper that was in the way and whether
# it was pre-existing. Read those, not the log prose - upstream keeps a test on
# that key precisely because a printed sentence is not something a gate can
# read, and an earlier run burned three grid refinements against one.
#
# Note what the classes do NOT come from: the iteration count. A net can search
# hard and still be boxed (a pad's own neighbours do not become passable after
# more search), and a net can fail fast for lack of a rippable blocker without
# being boxed at all. Iterations are recorded because they are interesting, and
# they decide nothing.
FAILURE_WORDS = {
    "terminal_blocked": "boxed at a terminal (the pad's own neighbours block it; "
                        "no placement move helps - change the escape, pitch or grid)",
    "blocked_by_copper": "blocked by other copper (named per net; a placement or "
                         "routing-order problem)",
    "multipoint_edge_failed": "a multi-pad net left pads unreached (they are named)",
    "unclassified": "the router failed it without a verdict - read the log",
    "not_attempted": "no routing attempt recorded for it",
}


def failures_by_net(work, only=None):
    """{net: {class, iterations, blocked_by, detail}} for nets still open.

    `work` is the trial work directory. Falls back to the router log only when
    the summary is missing (a record made before the router exported it).
    """
    summary_path = os.path.join(work, "router_summary.json")
    if not os.path.exists(summary_path):
        return _failures_from_log(os.path.join(work, "router.log"), only)
    try:
        s = json.load(open(summary_path))
    except Exception:
        return _failures_from_log(os.path.join(work, "router.log"), only)

    boxed = {}
    for e in s.get("boxed_in") or []:
        if e.get("net"):
            boxed[e["net"]] = e
    blockers = {}
    for e in s.get("blockers") or []:
        if e.get("net"):
            blockers.setdefault(e["net"], []).extend(e.get("blocked_by") or [])
    failed = set(s.get("failed_single") or [])
    multipoint = {}
    for e in s.get("failed_multipoint") or []:
        if isinstance(e, dict) and e.get("net_name"):
            failed.add(e["net_name"])
            multipoint[e["net_name"]] = e.get("failed_pads") or []
    # the router leaves a few failures without a structured verdict; its printed
    # conclusions are the last resort for those, and only those
    from_log = _failures_from_log(os.path.join(work, "router.log"), only)

    out = {}
    for net in (only if only is not None else set(boxed) | set(blockers) | failed):
        by = [b.get("net") for b in blockers.get(net, []) if b.get("net")]
        if net in boxed:
            # the two keys answer different questions: `blockers` says WHICH
            # copper is in the way, `boxed_in` says nothing rippable is, so a
            # net with both is still boxed
            e = boxed[net]
            out[net] = {"class": "terminal_blocked", "iterations": e.get("iterations"),
                        "blocked_by": sorted(set(by)),
                        "detail": "%s at grid %s / clearance %s / track %s"
                                  % (e.get("verdict", "boxed_in"),
                                     (e.get("geometry") or {}).get("grid_step"),
                                     (e.get("geometry") or {}).get("clearance"),
                                     (e.get("geometry") or {}).get("track_width"))}
        elif by:
            out[net] = {"class": "blocked_by_copper", "iterations": None,
                        "blocked_by": sorted(set(by)),
                        "detail": "blocked by " + ", ".join(sorted(set(by))[:6])}
        elif net in multipoint:
            pads = ["%s@%.1f,%.1f" % (p.get("component_ref", "?"), p.get("x", 0), p.get("y", 0))
                    for p in multipoint[net]]
            out[net] = {"class": "multipoint_edge_failed", "iterations": None,
                        "blocked_by": [], "failed_pads": pads,
                        "detail": "unreached: " + ", ".join(pads[:4])}
        elif net in failed:
            fb = from_log.get(net) or {}
            out[net] = {"class": fb.get("class", "unclassified"), "iterations": None,
                        "blocked_by": [], "detail": fb.get("detail", "")}
        else:
            out[net] = {"class": "not_attempted", "iterations": None,
                        "blocked_by": [], "detail": ""}
    return out


def _failures_from_log(log_path, only=None):
    """The pre-summary fallback: the router's printed conclusions."""
    if not os.path.exists(log_path):
        return {}
    blocks, cur = {}, None
    for line in open(log_path, errors="replace"):
        m = re.match(r"\[\d+/\d+[^\]]*\]\s+Routing\s+(\S+)", line)
        if m:
            cur = m.group(1)
            blocks.setdefault(cur, [])
        elif cur and (line.startswith(" ") or line.startswith("\t")):
            blocks[cur].append(line.strip())
    out = {}
    for net, lines in blocks.items():
        if only is not None and net not in only:
            continue
        text = " ".join(lines)
        if "FAILED" not in text and "failed" not in text:
            continue
        boxed = re.search(r"boxed in by static obstacles|terminal copper on \S+ would OVERLAP", text)
        out[net] = {"class": "terminal_blocked" if boxed else "unclassified",
                    "iterations": None, "blocked_by": [],
                    "detail": (boxed.group(0) if boxed else "")}
    for net in (only or ()):
        out.setdefault(net, {"class": "not_attempted", "iterations": None,
                             "blocked_by": [], "detail": ""})
    return out


def nets_in_violations(drc, kinds=("shorting_items", "clearance")):
    """Net names carried by DRC items of the given kinds (a track, via or
    polygon description reads 'Track [NET] on B.Cu ...')."""
    nets = set()
    for v in drc.get("violations", []):
        if v.get("type") in kinds:
            for i in v.get("items", []):
                m = re.search(r"\[([^\]]+)\]", i.get("description", ""))
                if m:
                    nets.add(m.group(1))
    return nets


def score(sig0, sig1, after, excluded):
    """Raw closure, clean closure, and the signal nets the router closed
    THROUGH a short or clearance violation (counted fully open in the clean
    number)."""
    items0, items1 = sum(sig0.values()), sum(sig1.values())
    shorted = sorted(n for n in nets_in_violations(after) if n in sig0 and n not in excluded)
    nets = set(sig0) | set(sig1)
    items1_clean = sum(sig0.get(n, sig1.get(n, 0)) if n in shorted else sig1.get(n, 0) for n in nets)
    closure = (1.0 - items1 / items0) if items0 else 1.0
    clean = (1.0 - items1_clean / items0) if items0 else 1.0
    return closure, clean, shorted


def rescore(work):
    """Recompute clean closure and validity for an existing work dir and
    update its record in place (older records carry only the raw closure)."""
    recs = [f for f in os.listdir(work) if f.endswith(".route_trial.json")]
    if len(recs) != 1:
        sys.exit("expected one *.route_trial.json in %s, found %d" % (work, len(recs)))
    rec_path = os.path.join(work, recs[0])
    rec = json.load(open(rec_path))
    excluded = set(rec["router"]["excluded_nets"])
    before = json.load(open(os.path.join(work, "drc_before.json")))
    after = json.load(open(os.path.join(work, "drc_after.json")))
    sig0 = {n: v for n, v in open_by_net(before).items() if n not in excluded}
    sig1 = {n: v for n, v in open_by_net(after).items() if n not in excluded}
    closure, clean, shorted = score(sig0, sig1, after, excluded)
    if abs(closure - rec["closure"]) > 0.001:
        sys.exit("recomputed raw closure %.4f differs from the record's %.4f; not the same run" % (closure, rec["closure"]))
    b_before = real_violations(before)
    rec["before"]["drc"] = b_before
    rec["valid"] = not b_before
    if b_before:
        rec["invalid_reason"] = "placement DRC not clean before routing: %s" % b_before
    else:
        rec.pop("invalid_reason", None)
    rec["closure_clean"] = round(clean, 4)
    rec["shorted_signal_nets"] = shorted
    json.dump(rec, open(rec_path, "w"), indent=1)
    print("%s: closure %.1f%%, %d net(s) routed through a violation %s, %s"
          % (rec_path, 100 * clean, len(shorted), shorted,
             "VALID" if rec["valid"] else "INVALID (%s)" % rec["invalid_reason"]))
    return rec


# ------------------------------------------------------ KiCad-python helpers
LOCK_AND_NETS = r'''
import json, sys, pcbnew
pcb, out = sys.argv[1], sys.argv[2]
b = pcbnew.LoadBoard(pcb)
n = 0
for t in b.GetTracks():
    t.SetLocked(True); n += 1
for d in b.GetDrawings():
    if d.GetClass() == "PCB_SHAPE" and d.IsOnCopperLayer():
        d.SetLocked(True); n += 1
b.Save(pcb)
nets = sorted(str(k) for k in b.GetNetInfo().NetsByName().keys() if str(k))
json.dump({"locked": n, "nets": nets, "copper_layers": b.GetCopperLayerCount()}, open(out, "w"))
'''

STATS_AND_ATTRIBUTION = r'''
import json, sys, collections, pcbnew

def _root():
    """The project's root. Asked for, never computed from this file's own path."""
    from placemat.project import active
    return active().root or os.getcwd()

pcb, nets_json, out = sys.argv[1], sys.argv[2], sys.argv[3]
want = set(json.load(open(nets_json)))
b = pcbnew.LoadBoard(pcb)
segs = [t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK"]
vias = [t for t in b.GetTracks() if t.GetClass() == "PCB_VIA"]
widths = collections.Counter(round(t.GetWidth() / 1e6, 3) for t in segs)
by_layer = collections.Counter(pcbnew.LayerName(t.GetLayer()) for t in segs)
via_sizes = collections.Counter(round(t.GetWidth() / 1e6, 2) for t in vias)
def path_of(fp):
    for f in fp.GetFields():
        if f.GetName() == "Path":
            return f.GetText()
    return ""
def cell_of(fp):
    parts = path_of(fp).split(".")
    return parts[0] if len(parts) >= 3 else "(loose)"
attr = {}
for net in want:
    pads = [(str(f.GetReference()), cell_of(f), "B" if f.IsFlipped() else "F")
            for f in b.GetFootprints() for p in f.Pads() if str(p.GetNetname()) == net]
    cells = sorted({c for _, c, _ in pads}); faces = sorted({f for _, _, f in pads})
    kind = ("module-internal" if len(cells) == 1 and cells[0] != "(loose)"
            else "cross-face" if len(faces) > 1 else "board-level")
    attr[net] = {"kind": kind, "pads": len(pads), "faces": faces, "cells": cells}
json.dump({"tracks": len(segs), "vias": len(vias),
           "min_track_width": min(widths) if widths else None,
           "track_widths": sorted(widths.items()), "via_sizes": sorted(via_sizes.items()),
           "segments_by_layer": dict(by_layer), "attribution": attr}, open(out, "w"))
'''


def kpy(interp, code, *args):
    r = subprocess.run([interp, "-c", code] + list(args), capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("KiCad python step failed:\n" + r.stderr[-2000:])


# --------------------------------------------------------------------- main

def parser():
    """The arguments this command takes."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("board", help="placed .kicad_pcb (its .kicad_pro must sit beside it)")
    ap.add_argument("--out", help="work dir (default <board dir>/route-trial)")
    ap.add_argument("--layers", nargs="+", default=["F.Cu", "B.Cu"],
                    help="layers the router may use (default: the two outer layers)")
    ap.add_argument("--exclude-classes", nargs="*", default=list(DEFAULT_EXCLUDED_CLASSES),
                    help="net classes routed by planes and pours, not by this gate")
    ap.add_argument("--exclude", nargs="*", default=[], help="extra net-name patterns to exclude")
    ap.add_argument("--iterations", type=int, default=150000, help="router iteration cap per attempt")
    ap.add_argument("--probe", type=int, default=3000, help="router probe iterations")
    ap.add_argument("--router", default=ROUTER_DEFAULT, help="KiCadRoutingTools checkout with .venv")
    ap.add_argument("--render", action="store_true", help="write top and bottom renders of the result")
    ap.add_argument("--quick", action="store_true",
                    help="ONE routing round (the router's reconciliation rounds off, via `placemat trial-round`): "
                         "about a third of the time for about the same closure; a number to iterate on, not to record")
    ap.add_argument("--film", action="store_true", help="record the router trace and replay it to a GIF")
    ap.add_argument("--keep-going", action="store_true", help="do not stop on a router version mismatch")
    ap.add_argument("--no-wait", action="store_true", help="exit instead of queueing when another trial holds the lock")
    ap.add_argument("--rescore", action="store_true",
                    help="the positional argument is a previous WORK DIR: recompute clean closure and validity into its record")
    return ap


def main(args=None):
    a = args if args is not None else parser().parse_args()
    if a.rescore:
        rescore(os.path.abspath(a.board))
        return 0

    board = os.path.abspath(a.board)
    if not os.path.exists(board):
        sys.exit("no such board: %s" % board)
    name = os.path.basename(os.path.dirname(board)) or "board"
    work = os.path.abspath(a.out or os.path.join(os.path.dirname(board), "route-trial"))
    os.makedirs(work, exist_ok=True)
    rpy = os.path.join(a.router, ".venv", "bin", "python")
    route_py = os.path.join(a.router, "py_router", "route.py")
    if not (os.path.exists(rpy) and os.path.exists(route_py)):
        sys.exit("router not found at %s (expected .venv/bin/python and py_router/route.py)" % a.router)
    if a.quick:
        route_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "route_one_round.py")
    ver = router_version(a.router)
    if ver != PINNED_ROUTER and not a.keep_going:
        sys.exit("router version %s differs from the pinned %s; results would not be comparable "
                 "(pass --keep-going to run anyway)" % (ver, PINNED_ROUTER))
    kp = kicad_python()

    # 0. one trial at a time per machine (the lock lives in the router checkout,
    #    which every session shares); released when this process exits
    lock_path = os.path.join(a.router, ".route_trial.lock")
    lock = open(lock_path, "a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.seek(0)
        holder = lock.read().strip() or "unknown"
        if a.no_wait:
            sys.exit("another route trial is running (%s); --no-wait given, not queueing" % holder)
        print("another route trial is running (%s); queued on %s" % (holder, lock_path), flush=True)
        fcntl.flock(lock, fcntl.LOCK_EX)
    lock.seek(0)
    lock.truncate()
    lock.write("pid %d  started %s  %s\n" % (os.getpid(), time.strftime("%Y-%m-%d %H:%M"), board))
    lock.flush()

    # 1. copy in
    src_base = board[:-len(".kicad_pcb")]
    pcb_in = os.path.join(work, name + ".kicad_pcb")
    shutil.copy(board, pcb_in)
    pro = None
    for ext in (".kicad_pro", ".kicad_dru"):
        if os.path.exists(src_base + ext):
            shutil.copy(src_base + ext, os.path.join(work, name + ext))
            if ext == ".kicad_pro":
                pro = os.path.join(work, name + ext)

    # 2. lock copper, list nets
    meta = os.path.join(work, "board_meta.json")
    kpy(kp, LOCK_AND_NETS, pcb_in, meta)
    meta = json.load(open(meta))
    explicit, patterns = netclass_map(pro)
    cls = {n: class_of(n, explicit, patterns) for n in meta["nets"]}
    excluded = {n for n, c in cls.items() if c in set(a.exclude_classes)}
    excluded |= {n for n in meta["nets"] if any(fnmatch.fnmatchcase(n, p) for p in a.exclude)}

    def split(counter):
        sig = {n: v for n, v in counter.items() if n not in excluded}
        pwr = {n: v for n, v in counter.items() if n in excluded}
        return sig, pwr

    # 3. DRC before
    before = run_drc(pcb_in, os.path.join(work, "drc_before.json"))
    sig0, pwr0 = split(open_by_net(before))
    b_before = real_violations(before)
    valid = not b_before
    if not valid:
        print("WARNING: placement DRC is not clean before routing (%s); the record will be marked INVALID" % b_before, flush=True)

    # 4. route
    pcb_out = os.path.join(work, name + ".routed.kicad_pcb")
    summary_json = os.path.join(work, "router_summary.json")
    cmd = [rpy, route_py, pcb_in, pcb_out, "--nets", "*"] + ["!" + n for n in sorted(excluded)] + \
          ["--layers"] + a.layers + ["--escalation", "off", "--max-iterations", str(a.iterations),
                                     "--max-probe-iterations", str(a.probe), "--json-out", summary_json]
    # The scored run never carries the trace flag, so a film can never alter a
    # score; the film comes from a second, separate run whose copper is discarded.
    # (The trace flag does not change the result; item order in the input file
    # does, so baselines are taken on a fresh regeneration, the way rounds are.)
    env = dict(os.environ)
    env.pop("KICAD_ROUTE_TRACE", None)
    env["KRT_DIR"] = a.router
    t0 = time.time()
    with open(os.path.join(work, "router.log"), "w") as log:
        rc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=a.router, env=env).returncode
    elapsed = time.time() - t0
    if rc != 0 or not os.path.exists(pcb_out):
        sys.exit("router failed (exit %d); see %s" % (rc, os.path.join(work, "router.log")))
    film_pcb = None
    if a.film:
        film_pcb = os.path.join(work, name + ".film.kicad_pcb")
        fenv = dict(os.environ); fenv["KICAD_ROUTE_TRACE"] = "1"
        fcmd = list(cmd); fcmd[3] = film_pcb
        fcmd = [x for x in fcmd if x != "--json-out" and x != summary_json]
        with open(os.path.join(work, "router_film.log"), "w") as log:
            subprocess.run(fcmd, stdout=log, stderr=subprocess.STDOUT, cwd=a.router, env=fenv)
    for ext in (".kicad_pro", ".kicad_dru"):
        if os.path.exists(os.path.join(work, name + ext)):
            shutil.copy(os.path.join(work, name + ext), pcb_out[:-len(".kicad_pcb")] + ext)
    rsum = json.load(open(summary_json)) if os.path.exists(summary_json) else {}

    # 5. DRC after
    after = run_drc(pcb_out, os.path.join(work, "drc_after.json"))
    sig1, pwr1 = split(open_by_net(after))
    b_after = buckets(after)

    # 6. stats + attribution of every signal net still open
    open_nets = sorted(sig1)
    nets_json = os.path.join(work, "open_nets.json")
    json.dump(open_nets, open(nets_json, "w"))
    stats_json = os.path.join(work, "stats.json")
    kpy(kp, STATS_AND_ATTRIBUTION, pcb_out, nets_json, stats_json)
    stats = json.load(open(stats_json))
    attr = stats.pop("attribution")
    by_kind = collections.Counter(v["kind"] for v in attr.values())
    cell_hits = collections.Counter(c for v in attr.values() for c in v["cells"])

    why_open = failures_by_net(work, only=set(open_nets))

    items0, items1 = sum(sig0.values()), sum(sig1.values())
    closure, closure_clean, shorted = score(sig0, sig1, after, excluded)
    result = {
        "board": board, "work": work, "date": time.strftime("%Y-%m-%d %H:%M"),
        "router": {"path": a.router, "version": ver, "layers": a.layers, "escalation": "off", "quick": bool(a.quick),
                   "max_iterations": a.iterations, "probe_iterations": a.probe, "seconds": round(elapsed, 1),
                   "excluded_classes": a.exclude_classes, "excluded_nets": sorted(excluded),
                   "locked_items": meta["locked"]},
        "before": {"signal_open_items": items0, "signal_open_nets": len(sig0),
                   "plane_open_items": sum(pwr0.values()), "plane_open_nets": len(pwr0), "drc": b_before},
        "after": {"signal_open_items": items1, "signal_open_nets": len(sig1),
                  "plane_open_items": sum(pwr1.values()), "drc": b_after},
        "valid": valid,
        "closure": round(closure, 4),
        "closure_clean": round(closure_clean, 4),
        "shorted_signal_nets": shorted,
        "copper": stats,
        "router_failed_single": rsum.get("failed_single", []),
        "router_failed_multipoint": [x.get("net_name") for x in rsum.get("failed_multipoint", [])],
        "open_signal_nets": {n: dict(items=sig1[n], **attr.get(n, {})) for n in open_nets},
        "why_open": why_open,
        "why_open_counts": dict(collections.Counter(v["class"] for v in why_open.values())),
        "by_kind": dict(by_kind), "cells_involved": cell_hits.most_common(),
    }
    if not valid:
        result["invalid_reason"] = "placement DRC not clean before routing: %s" % b_before
    out_json = os.path.join(work, name + ".route_trial.json")
    json.dump(result, open(out_json, "w"), indent=1)

    # 7. optional artefacts
    if a.render:
        for side in ("top", "bottom"):
            subprocess.run(["kicad-cli", "pcb", "render", "--side", side, "--background", "opaque",
                            "--quality", "high", "--zoom", "1.0", "-o",
                            os.path.join(work, "%s.routed_%s.png" % (name, side)), pcb_out],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if a.film and film_pcb and os.path.exists(film_pcb):
        trace = film_pcb[:-len(".kicad_pcb")] + "_routetrace.json"
        anim = os.path.join(a.router, "py_router", "animate_route.py")
        if os.path.exists(trace) and os.path.exists(anim):
            subprocess.run([rpy, anim, trace, "--board", film_pcb, "-o",
                            os.path.join(work, name + ".routing.gif")],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=a.router)

    # 8. report
    print("route trial%s: %s  (router %s, layers %s, escalation off, %d iterations, %.0f s)%s"
          % (" (quick, one round)" if a.quick else "", name, ver, " ".join(a.layers), a.iterations, elapsed,
             "" if valid else "   INVALID: placement DRC not clean before routing %s" % b_before))
    print("  signal open items: %d on %d nets  ->  %d on %d nets   closure %.1f%%"
          % (items0, len(sig0), items1, len(sig1), 100 * closure_clean))
    if shorted:
        print("  %d signal net(s) routed through a short or clearance violation, counted open in the clean number: %s"
              % (len(shorted), ", ".join(shorted)))
    print("  plane/pour nets excluded: %d nets, %d open items (not this gate's job)"
          % (len(excluded), sum(pwr0.values())))
    print("  copper: %d tracks (min width %.3f), %d vias; by layer %s"
          % (stats["tracks"], stats["min_track_width"] or 0, stats["vias"], stats["segments_by_layer"]))
    print("  DRC after: %s" % (real_violations(after) or "clean"))
    print("  open signal nets by kind: %s" % dict(by_kind))
    print("  cells involved: %s" % cell_hits.most_common(8))
    for n in open_nets[:40]:
        v = attr.get(n, {})
        print("    %-26s %-16s pads=%-3s faces=%-4s cells=%s"
              % (n, v.get("kind", "?"), v.get("pads", "?"), "+".join(v.get("faces", [])), ",".join(v.get("cells", []))))
    if len(open_nets) > 40:
        print("    ... %d more in %s" % (len(open_nets) - 40, out_json))
    print("  summary: %s" % out_json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
