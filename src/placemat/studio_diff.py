"""What changed between two resolves, for `placemat studio`'s compare: the
plans (as preview_json.plan_json writes them), the script's text, and the
trace between the two - which changed lines declare which moved items.

Pure. `diff_plans` works on any two documents with an `items` list of
{key, at, rotation, face}: a whole plan, or a partial set of placements (an
explore variant lists only the items it varied), so the same diff and the
same page rendering serve both."""
from __future__ import annotations

import ast
from collections import Counter
import difflib
import functools
import json


def _state(item: dict) -> dict:
    """Where an item stands: its place, rotation, face and, for a cell in one of its module's other arrangements, that arrangement."""
    return {"at": item.get("at"), "rotation": item.get("rotation"), "face": item.get("face"),
            **({"arrangement": item["arrangement"]} if item.get("arrangement") else {})}


def _distance(a, b) -> float:
    if not a or not b:
        return 0.0
    return round(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5, 3)


def _ops(doc: dict) -> Counter:
    return Counter(json.dumps(op, sort_keys=True) for op in doc.get("copper", ()))


def _delta(a: Counter, b: Counter) -> list:
    """The ops `a` has more of than `b`, in a's order of first appearance."""
    left = Counter(a)
    left.subtract(b)
    out = []
    for text in a:
        for _ in range(max(left[text], 0)):
            out.append(json.loads(text))
        left[text] = 0
    return out


def _texts(doc: dict) -> Counter:
    return Counter(f["text"] for f in doc.get("findings", ()))


def _findings(doc: dict, texts) -> list:
    keep = Counter(texts)
    out = []
    for f in doc.get("findings", ()):
        if keep[f["text"]] > 0:
            keep[f["text"]] -= 1
            out.append(f)
    return out


def _links(doc: dict) -> dict:
    return {(tuple(l["a"]), tuple(l["b"])): l for l in doc.get("links", ())}


def diff_plans(a: dict, b: dict, partial: bool = False) -> dict:
    """What `b` changed from `a`: items moved (both places), added and removed,
    copper drawn in one state and not the other, links whose length or state
    changed, findings gained and lost, the score and the worst congestion.
    With `partial`, `b` is a subset of placements: only the items in both are
    compared, and nothing is reported added, removed or changed beyond them."""
    ia = {i["key"]: i for i in a.get("items", ())}
    ib = {i["key"]: i for i in b.get("items", ())}
    unplaced_a = {u["item"] for u in a.get("unplaced", ())}
    unplaced_b = {u["item"] for u in b.get("unplaced", ())}
    moved, added, removed = [], [], []
    for key, new in ib.items():
        old = ia.get(key)
        if old is None:
            if not partial:
                added.append({"key": key, **_state(new), "file": new.get("file", ""), "line": new.get("line", 0),
                              "was_unplaced": key in unplaced_a})
        elif _state(old) != _state(new):
            moved.append({"key": key, "from": _state(old), "to": _state(new), "distance": _distance(old.get("at"), new.get("at")),
                          "turned": old.get("rotation") != new.get("rotation"), "flipped": old.get("face") != new.get("face"),
                          "rearranged": (old.get("arrangement") or "") != (new.get("arrangement") or "")})
    if not partial:
        for key, old in ia.items():
            if key not in ib:
                removed.append({"key": key, **_state(old), "file": old.get("file", ""), "line": old.get("line", 0),
                                "now_unplaced": key in unplaced_b})
    out = {"moved": moved, "added": added, "removed": removed,
           "copper": {"added": [], "removed": []}, "links": [], "findings": {"gained": [], "lost": []},
           "score": None, "congestion": None}
    if not partial:
        ca, cb = _ops(a), _ops(b)
        out["copper"] = {"added": _delta(cb, ca), "removed": _delta(ca, cb)}
        la, lb = _links(a), _links(b)
        for k in lb:
            if k in la and (la[k]["length"], la[k]["state"]) != (lb[k]["length"], lb[k]["state"]):
                out["links"].append({"a": list(k[0]), "b": list(k[1]), "from": {"length": la[k]["length"], "state": la[k]["state"]},
                                     "to": {"length": lb[k]["length"], "state": lb[k]["state"]}})
        ta, tb = _texts(a), _texts(b)
        out["findings"] = {"gained": _findings(b, tb - ta), "lost": _findings(a, ta - tb)}
        sa, sb = a.get("score"), b.get("score")
        if sa and sb and "total" in sa and "total" in sb:
            out["score"] = {"a": sa["total"], "b": sb["total"], "delta": round(sb["total"] - sa["total"], 3)}
        xa, xb = a.get("congestion"), b.get("congestion")
        if xa and xb and xa["worst"] != xb["worst"]:
            out["congestion"] = {"a": xa["worst"], "b": xb["worst"]}
    out["empty"] = not (moved or added or removed or out["copper"]["added"] or out["copper"]["removed"] or out["links"]
                        or out["findings"]["gained"] or out["findings"]["lost"] or out["score"] and out["score"]["delta"]
                        or out["congestion"])
    return out


# ------------------------------------------------------------------ lines

def unified_diff(old: str, new: str, name: str = "", context: int = 3) -> str:
    """The usual unified diff text, "" when the texts are equal."""
    rows = difflib.unified_diff(old.splitlines(True), new.splitlines(True), name, name, n=context)
    return "".join(r if r.endswith("\n") else r + "\n" for r in rows)


def line_diff(old: str, new: str, context: int = 3) -> dict:
    """The change from `old` to `new` as hunks of numbered lines (each row
    {tag " " | "-" | "+", old, new, text}), the line numbers changed on each
    side, and the counts."""
    a, b = old.splitlines(), new.splitlines()
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    changed_new, changed_old = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            changed_old += range(i1 + 1, i2 + 1)
            changed_new += range(j1 + 1, j2 + 1)
    hunks = []
    for group in sm.get_grouped_opcodes(context):
        rows = []
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                rows += [{"tag": " ", "old": i + 1, "new": j + 1, "text": a[i]} for i, j in zip(range(i1, i2), range(j1, j2))]
                continue
            rows += [{"tag": "-", "old": i + 1, "new": None, "text": a[i]} for i in range(i1, i2)]
            rows += [{"tag": "+", "old": None, "new": j + 1, "text": b[j]} for j in range(j1, j2)]
        first, last = group[0], group[-1]
        hunks.append({"old_start": first[1] + 1, "old_len": last[2] - first[1], "new_start": first[3] + 1,
                      "new_len": last[4] - first[3], "lines": rows})
    return {"hunks": hunks, "changed_new": changed_new, "changed_old": changed_old,
            "added": len(changed_new), "removed": len(changed_old)}


@functools.lru_cache(maxsize=16)
def _statement_spans(text: str) -> tuple | None:
    """Each statement's (start, end) lines in `text`, in ast.walk order, a
    compound statement's end being its header's last line; None when the
    text does not parse. Keyed on the whole text, so one parse serves every
    item a file declares, and the next resolve when the file is unchanged."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.stmt):
            continue
        start, end = node.lineno, node.end_lineno or node.lineno
        body = getattr(node, "body", None)
        if isinstance(body, list) and body:
            end = max(start, body[0].lineno - 1)        # the header: up to the line before its body
        out.append((start, end))
    return tuple(out)


def declaration_span(text: str, line: int) -> tuple:
    """The lines of the statement that holds `line`: what a declaration is,
    whichever of its lines the interpreter named. A compound statement is its
    header alone. (line, line) when the text does not parse."""
    spans = _statement_spans(text)
    if spans is None:
        return (line, line)
    best = None
    for start, end in spans:
        if start <= line <= end and (best is None or end - start <= best[1] - best[0]):
            best = (start, end)
    return best if best is not None else (line, line)


def with_spans(doc: dict, texts: dict) -> dict:
    """`doc` with each item's `span` - the statement that declared it, in the
    text of its file - added. The original is left alone: the items are
    copied, the rest of the document is shared."""
    out = dict(doc)
    if "items" in doc:
        items = []
        for item in doc["items"]:
            text = texts.get(item.get("file"))
            if text is not None and item.get("line"):
                item = dict(item, span=list(declaration_span(text, item["line"])))
            items.append(item)
        out["items"] = items
    return out


# ------------------------------------------------------------------ trace

def _within(lines, span) -> list:
    return [n for n in lines if span[0] <= n <= span[1]]


def trace(d: dict, a: dict, b: dict, files: dict) -> dict:
    """The links between a plan diff `d` of `a` and `b` (documents given
    their spans by with_spans) and the line diffs `files` ({file: line_diff}):
    for each moved, added or removed item, the changed lines inside its
    declaration, on each side; for each changed line, the items it moved.
    Items whose declaration did not change are `knock_on`: moved by something
    else the change did."""
    ia = {i["key"]: i for i in a.get("items", ())}
    ib = {i["key"]: i for i in b.get("items", ())}
    out = {"items": {}, "lines": {}, "knock_on": []}

    def side(item, ld, which):
        if item is None or ld is None or not item.get("line"):
            return []
        span = item.get("span") or [item["line"], item["line"]]
        return _within(ld["changed_" + which], span)

    for kind in ("moved", "added", "removed"):
        for entry in d[kind]:
            key = entry["key"]
            old, new = ia.get(key), ib.get(key)
            found = {"new": side(new, files.get((new or {}).get("file")), "new"),
                     "old": side(old, files.get((old or {}).get("file")), "old")}
            out["items"][key] = {"kind": kind, "files": sorted({(new or {}).get("file", ""), (old or {}).get("file", "")} - {""}),
                                 "span": (new or old or {}).get("span"), "lines": found}
            if not found["new"] and not found["old"]:
                out["knock_on"].append(key)
            for which, item in (("new", new), ("old", old)):
                for n in found[which]:
                    out["lines"].setdefault(item["file"], {"new": {}, "old": {}})[which].setdefault(str(n), []).append(key)
    return out
