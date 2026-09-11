#!/usr/bin/env python3
"""Each module's clearance floor, derived from the boards that stamp it.

A module fragment carries no net classes, so DRC on a fragment alone judges
every pair at the fragment's own default - which can be looser than what a
consuming board applies to the same copper. The floor a cell must hold is the
strictest class clearance any board assigns to its nets, and that is not a
number anyone should maintain by hand: the boards already declare it in their
`NetClass` lines.

How the mapping works: `pcb layout` stamps a cell's footprints with a `Path`
property of `<instance>.<path inside the fragment>`, so every pad on a board
traces back to the pad in the fragment that produced it. Reading the board's
net class for that pad yields the clearance that pad's net must hold, keyed by
the net's name INSIDE the module - no net-name mapping needed, and a rename on
either side cannot silently break it.

What stays hand-written is only what no board can express, and it lives with
the module in `<module dir>/clearance.json`:

  * `floor` / `nets` RAISE a floor above the class. A module-local net can
    carry a rail's potential under a local name (an ORing cell's internal pass
    copper is at bus potential but the board sees `idiode.VS`, Default class),
    and only a human knows that.
  * `accept` excuses a named pair BELOW the floor, with the arithmetic showing
    the part's own geometry forbids it (a 0.4 mm-pitch package with 0.2 mm pads
    is 0.200 pad-to-pad by construction).

A module no board stamps yet has nothing to derive from and falls back to the
strictest Default-class clearance the boards declare.
"""
import glob
import json
import os
import re
import sys

sys.dont_write_bytecode = True   # no __pycache__ beside the sources

import pcbnew                                                    # noqa: E402
from placemat import layout_oracle                                             # noqa: E402

FALLBACK_FLOOR = 0.20            # used only when no board declares a Default class


def repo_root(start=None):
    """The directory holding pcb.toml, or a hard error - this caller cannot
    work without one. One implementation, in project; this copy also climbed
    `while d != "/"`, which is not how a filesystem root is recognised."""
    from placemat import project
    root = project.repo_root(start)
    if root is None:
        raise RuntimeError("no pcb.toml above %s" % (start or __file__))
    return root


def _for(root):
    """The project this call is about: the active one, or one built for `root`."""
    from placemat import project
    if root is None:
        return project.active()
    a = project.active()
    return a if a.root and os.path.abspath(root) == a.root else project.Project(root=root)


def boards(root=None):
    """(board .zen sources, generated layout) for every generated board.

    The PROJECT answers this, so there is one place that knows the shape of a
    repo and one definition of what counts as a board."""
    return _for(root).generated_boards()


def instances(zen_paths):
    """(exact, prefixes) for every module a board instantiates.

    Reads the two lines that carry it: the alias (`X = Module("../modules/Y/Y.zen")`)
    and the instantiation (`X(name = "inst", ...)`). A board that stamps a cell
    in a loop writes `X(name = "drop" + str(d), ...)`, so a name followed by `+`
    is a PREFIX, matched against the board's instance names longest-first.
    """
    alias, exact, prefix = {}, {}, {}
    for zen in zen_paths:
        src = open(zen).read()
        for name, path in re.findall(r'^(\w+)\s*=\s*Module\("([^"]+)"\)', src, re.M):
            alias[name] = os.path.splitext(os.path.basename(path))[0]
        for name, iname, plus in re.findall(r'\b(\w+)\(\s*name\s*=\s*"([^"]*)"(\s*\+)?', src):
            if name not in alias:
                continue
            (prefix if plus else exact)[iname] = alias[name]
    return exact, prefix


def module_of(iname, exact, prefix):
    """The module an instance name belongs to, exact match before longest prefix."""
    if iname in exact:
        return exact[iname]
    for p in sorted(prefix, key=len, reverse=True):
        if p and iname.startswith(p):
            return prefix[p]
    return None


def module_dirs(root=None):
    """{module name: its folder}. The project answers it; this is the old name."""
    return _for(root).module_dirs


def fragment_pad_nets(frag_pcb):
    """{(path in fragment, pad number): net name} for one module fragment."""
    b = pcbnew.LoadBoard(frag_pcb)
    out = {}
    for fp in b.GetFootprints():
        path = fp.GetFieldsText().get("Path", "")
        for pad in fp.Pads():
            out[(path, pad.GetNumber())] = pad.GetNetname()
    return out


def _default_clearance(pcb):
    """The board's Default net class clearance, read from its project file."""
    pro = os.path.splitext(pcb)[0] + ".kicad_pro"
    try:
        cls = json.load(open(pro))["net_settings"]["classes"]
    except Exception:
        return None
    for c in cls:
        if c.get("name") == "Default":
            return c.get("clearance")
    return None


def derive(root=None, verbose=False):
    """{module: {net inside the module: required clearance mm}}.

    Every board that stamps a cell contributes; the strictest wins.
    """
    root = root or repo_root()
    mdirs = module_dirs(root)
    found = boards(root)
    if not found:
        print("clearance_floors: no generated board layouts under %s - every "
              "module falls back to %.2f mm, so an HV cell is UNDER-checked. "
              "Generate a board first." % (root, FALLBACK_FLOOR), file=sys.stderr)
    frag_cache = {}
    floors = {}
    used = {}
    unresolved = {}
    default = FALLBACK_FLOOR

    for zens, pcb in found:
        exact, prefix = instances(zens)
        if not exact and not prefix:
            continue
        b = pcbnew.LoadBoard(pcb)
        o = layout_oracle.Oracle(b, path=pcb)
        # a stamped cell is a GROUP on the board; a loose part shares the
        # <instance>.<part> path shape but is not one, so only a group name
        # that no module claims is a real miss worth reporting
        groups = set(g.GetName() for g in b.Groups())
        d = _default_clearance(pcb)
        if d:
            default = max(default, d)
        clr = {}                                  # net -> clearance, per board

        for fp in b.GetFootprints():
            path = fp.GetFieldsText().get("Path", "")
            if "." not in path:
                continue
            iname = path.split(".", 1)[0]
            module = module_of(iname, exact, prefix)
            if module is None:
                if iname in groups:
                    unresolved.setdefault(os.path.basename(os.path.dirname(pcb)), set()).add(iname)
                continue
            if module not in mdirs:
                continue
            frag = os.path.join(mdirs[module], "layout", "layout.kicad_pcb")
            if not os.path.exists(frag):
                continue
            if frag not in frag_cache:
                frag_cache[frag] = fragment_pad_nets(frag)
            local_path = path.split(".", 1)[1]

            for pad in fp.Pads():
                net = pad.GetNetname()
                if not net:
                    continue
                if net not in clr:
                    try:
                        clr[net] = o.netclass(net)["clearance"]
                    except KeyError:
                        clr[net] = None
                if clr[net] is None:
                    continue
                local = frag_cache[frag].get((local_path, pad.GetNumber()))
                if local is None:
                    continue
                cur = floors.setdefault(module, {})
                if clr[net] > cur.get(local, 0):
                    cur[local] = clr[net]
                used.setdefault(module, set()).add(os.path.basename(os.path.dirname(pcb)))

    for board, names in sorted(unresolved.items()):
        print("clearance_floors: %s stamps %d instance(s) no module claims: %s"
              % (board, len(names), ", ".join(sorted(names))), file=sys.stderr)
    if verbose:
        for m in sorted(floors):
            print("%-22s from %s" % (m, ",".join(sorted(used.get(m, ())))))
            for n, v in sorted(floors[m].items(), key=lambda kv: (-kv[1], kv[0])):
                print("    %-22s %.2f" % (n, v))
    return floors, default, {m: sorted(s) for m, s in used.items()}


def overrides(module_dir):
    """The module's hand-written raises and waivers, if it has any."""
    p = os.path.join(module_dir, "clearance.json")
    return json.load(open(p)) if os.path.exists(p) else {}


def config(root=None):
    """The floor table in the shape the clearance gate consumes:

        {"default_floor": mm, "modules": {name: {floor, nets, accept, why}}}

    Derived per net from the boards, then raised by the module's own
    clearance.json where a human has recorded a reason the classes cannot
    express.
    """
    root = root or repo_root()
    derived, default, used = derive(root)
    mdirs = module_dirs(root)
    modules = {}
    for name, d in mdirs.items():
        ov = overrides(d)
        nets = dict(derived.get(name, {}))
        for net, v in (ov.get("nets") or {}).items():
            nets[net] = max(v, nets.get(net, 0))
        entry = {"floor": max(ov.get("floor", 0), default),
                 "nets": nets,
                 "accept": ov.get("accept", []),
                 "derived_from": used.get(name, [])}
        if ov.get("why"):
            entry["why"] = ov["why"]
        modules[name] = entry
    return {"default_floor": default, "modules": modules}


if __name__ == "__main__":
    root = repo_root()
    floors, default, used = derive(root, verbose=True)
    print("\ndefault (Default class, strictest across boards): %.2f" % default)
    print("modules stamped on a board: %d" % len(floors))
    unstamped = sorted(set(module_dirs(root)) - set(floors))
    if unstamped:
        print("not stamped anywhere (fall back to the default): %s" % ", ".join(unstamped))
