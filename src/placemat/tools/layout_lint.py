#!/usr/bin/env python3
"""Does a layout script match the current standard, or does it predate it?

Why: the library grows one board at a time. The script being worked on gets the
new primitive; the other scripts keep the hand-rolled version they were written
with, and nobody sees the gap until they open the file. That is how a set of
scripts becomes a mixture - each one half library calls and half local code,
none of them readable against the others.

So conformance is measured, not remembered. Every finding names the line, what
it is, and the library call that replaces it. A finding is a CANDIDATE, not a
verdict: the migration rule (skill process step 0) is replace what the library
covers, propose what it does not, and this tool cannot tell the two apart.

  placemat lint <script.py> [...]   # named scripts
  placemat lint --all               # every board and module script
  placemat lint --all --format json
  placemat lint <script.py> --strict   # exit 1 on any finding
"""
import argparse

from placemat.args import script as script_arg
import ast
import json
import os
import re
import sys

def _root():
    """The project's root. Asked for, never computed from this file's own path."""
    from placemat.project import active
    return active().root or os.getcwd()


LIBRARY = ("modules/layout_helpers.py", "modules/board_layout.py",
           "modules/geometry.py", "modules/layout_oracle.py")

# Each rule is (id, regex, what it is, the call that replaces it). The message
# names a REPLACEMENT because a finding with no destination is just a complaint.
RULES = (
    ("units", r"/ *1e6|\* *1e6",
     "raw internal-unit conversion", "to_mm() / from_mm()"),
    ("vector", r"pcbnew\.VECTOR2I\(",
     "raw pcbnew vector", "point(), or the place/move helper that owns the motion"),
    ("shape", r"pcbnew\.PCB_SHAPE\(",
     "board graphics built by hand", "board.edge() / board.outline_* / layout.poly()"),
    ("zone", r"pcbnew\.ZONE\(",
     "zone built by hand", "board.plane() for copper, board.rule_area() for a keepout"),
    ("add", r"\bb\.Add\(",
     "item added to the board directly", "the library call that creates that item"),
    ("place_raw", r"\.SetPosition\(|\.SetOrientationDegrees\(",
     "footprint moved by hand", "board.place() / board.fix() / board.stamp()"),
    ("groups", r"GetName\(\): *g for g in",
     "group dict rebuilt", "board.cells (the library already indexes the groups)"),
    ("loose", r"not in _ingrp|_ingrp *=",
     "loose-footprint set rebuilt", "board.loose()"),
    ("padloop", r"for +\w+ +in +[\w\.\[\]\"']+\.Pads\(\)[^\n]*GetNetname\(\)",
     "pad looked up by walking Pads()", "L.pad_xy() / layout.pad_boxes() / layout._pad()"),
    ("render", r"L\.render\(|LAYOUT_RENDER",
     "render driven from the script", "L.both_faces = True, and let save() render"),
    ("sibling", r"open\([^)]*\.kicad_[a-z]+[^)]*, *[\"']w[\"']\)",
     "sibling board file written as text", "board.design_rule() / the save hooks"),
)

# The shape the scaffold fixes (references/scaffold_layout.py in the skill).
SHAPE = (
    ("config_split", r"^# =+$",
     "no config/mechanism divider", "the scaffold's two banner sections"),
    ("require_nets", r"require_nets\(",
     "net names never validated", "board.require_nets(): a rename is otherwise silent"),
)


def library_api(root):
    """Every public function and method the library exposes, by name."""
    api = {}
    for rel in LIBRARY:
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            continue
        try:
            tree = ast.parse(open(path, encoding="utf-8").read(), rel)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
                api.setdefault(node.name, rel)
    return api


def lint(path, api):
    src = open(path, encoding="utf-8").read()
    lines = src.splitlines()
    out = []
    for rid, pat, what, fix in RULES:
        rx = re.compile(pat)
        for i, line in enumerate(lines, 1):
            if line.lstrip().startswith("#"):
                continue                      # a comment naming an idiom is not using it
            if not rx.search(line):
                continue
            # A judged exception is recorded on the line, with its reason:
            #   ...code...   # lint-ok: <rule> - why the library call does not fit
            # It stays visible (counted and listed) rather than disappearing -
            # a silent waiver is how a standard rots.
            waiver = re.search(r"#\s*lint-ok:\s*([a-z_]+)\s*-\s*(.+)$", line)
            if waiver and waiver.group(1) == rid:
                out.append({"line": i, "rule": rid, "what": what, "use": fix,
                            "waived": waiver.group(2).strip(), "text": line.strip()[:90]})
                continue
            out.append({"line": i, "rule": rid, "what": what, "use": fix,
                        "text": line.strip()[:90]})
    # The scaffold shapes a BOARD script. A module fragment script has no
    # frame, no cells and no board nets, so its shape is its own question.
    is_board = "BoardLayout(" in src
    for rid, pat, what, fix in SHAPE:
        if is_board and not re.search(pat, src, re.M):
            out.append({"line": 0, "rule": rid, "what": what, "use": fix, "text": ""})

    # Mechanism still living in the script. A local def is not wrong by itself -
    # board-specific composition belongs here - but each one is a question the
    # migration has to answer: is this the library's job, under another name?
    try:
        tree = ast.parse(src, os.path.basename(path))
    except SyntaxError as e:
        out.append({"line": e.lineno or 0, "rule": "syntax", "what": "does not parse",
                    "use": "", "text": str(e)[:90]})
        return out
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # A STAGE BODY IS NOT A LOCAL HELPER. Under the stage framework a
            # script IS a set of decorated bodies - that is the standard, not a
            # divergence from it - so flagging them inverts this check's whole
            # purpose and tells a migrated board to migrate away from the
            # format it was just brought onto.
            if any(isinstance(d, ast.Call) and getattr(d.func, "id", "") == "stage"
                   or getattr(d, "id", "") == "stage" for d in node.decorator_list):
                continue
            hit = api.get(node.name.lstrip("_"))
            out.append({"line": node.lineno, "rule": "local_def",
                        "what": "local helper '%s'%s" % (node.name,
                                                         " - the library has this name" if hit else ""),
                        "use": ("%s (%s)" % (node.name, hit)) if hit else
                               "check the library BY CONCEPT; propose it if genuinely new",
                        "text": ""})
    return out



def parser():
    """The arguments this command takes."""
    ap = argparse.ArgumentParser()
    ap.add_argument("scripts", nargs="*", type=script_arg, help="board names, or paths to layout scripts")
    ap.add_argument("--all", action="store_true", help="every *_layout.py under the repo")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    ap.add_argument("--strict", action="store_true", help="exit 1 when anything is found")
    return ap


def main(args=None):
    a = args if args is not None else parser().parse_args()

    paths = [os.path.abspath(p) for p in a.scripts]
    if a.all:
        for base, dirs, files in os.walk(_root()):
            dirs[:] = [d for d in dirs if d not in (".git", "archive", "layout", ".pcb", ".rounds")]
            paths += [os.path.join(base, f) for f in files
                      if f.endswith("_layout.py")
                      and os.path.relpath(os.path.join(base, f), _root()) not in LIBRARY]
    paths = sorted(set(paths))
    if not paths:
        ap.error("name a script, or --all")

    api = library_api(_root())
    report = {}
    for p in paths:
        report[os.path.relpath(p, _root())] = lint(p, api)

    if a.format == "json":
        json.dump(report, sys.stdout, indent=1)
        print()
    else:
        for rel in sorted(report):
            waived = [f for f in report[rel] if f.get("waived")]
            found = [f for f in report[rel] if not f.get("waived")]
            for f in waived:
                print("%s:%d waived %s - %s" % (rel, f["line"], f["rule"], f["waived"]))
            if not found:
                print("%s: conforms" % rel)
                continue
            buckets = {}
            for f in found:
                buckets.setdefault(f["rule"], []).append(f)
            print("%s: %d finding(s) in %d kind(s)" % (rel, len(found), len(buckets)))
            for rule in sorted(buckets):
                fs = buckets[rule]
                where = ", ".join(str(f["line"]) for f in fs[:6]) + (" ..." if len(fs) > 6 else "")
                if rule == "local_def":
                    names = ", ".join(f["what"].split("'")[1] for f in fs)
                    print("  %-11s %d local helper(s): %s" % (rule, len(fs), names[:120]))
                    known = [f for f in fs if "the library has this name" in f["what"]]
                    for f in known:
                        print("  %-11s -> %s IS in the library: %s" % ("", f["what"].split("'")[1], f["use"]))
                    print("  %-11s -> check the rest BY CONCEPT; propose what is genuinely new" % "")
                    continue
                print("  %-11s %-46s line %s" % (rule, fs[0]["what"][:46], where))
                if fs[0]["use"]:
                    print("  %-11s -> %s" % ("", fs[0]["use"]))
    return 1 if (a.strict and any(report.values())) else 0


if __name__ == "__main__":
    sys.exit(main())
