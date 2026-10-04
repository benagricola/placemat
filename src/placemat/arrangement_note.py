"""The fragment's arrangement notes: one User.Comments text (or several numbered ones) per offered non-default arrangement,
`placemat arrangement <escaped json>`, the transport the faces and the clearance rules already use (pcb layout stamps it with
the cell). The document holds the members' places in the fragment's frame, the module's own copper as ops (the codec for the
copper.py records the writer reads back), the rule areas, and the default places the stamping board measures its offset by.

Like a rule note, the json is percent-escaped: KiCad reads braces and `$` in a text as markup."""
from __future__ import annotations

import hashlib
import json
from urllib.parse import quote, unquote

from .copper import Pour, Text, Track, Via, Zone
from .placement import Placement
from .values import CopperLayer, Face, Location

ARRANGEMENT_PREFIX = "placemat arrangement "
VERSION = 1
_SAFE = ",:[]._-"


class NoteError(Exception):
    pass


def _r(v: float, places: int = 6) -> float:
    return round(float(v), places)


def _pt(p) -> list:
    return [_r(p.x), _r(p.y)] if isinstance(p, Location) else [_r(p[0]), _r(p[1])]


def _loc(v) -> Location:
    return Location(float(v[0]), float(v[1]))


def pose_json(p: Placement) -> list:
    return [_r(p.location.x, 4), _r(p.location.y, 4), _r(p.rotation, 4), p.face.value]


def pose_from_json(v) -> Placement:
    return Placement(Location(float(v[0]), float(v[1])), float(v[2]), Face(v[3]))


def op_to_json(op) -> dict:
    if isinstance(op, Track):
        d = {"kind": "track", "net": op.net, "layer": op.layer.value, "width": _r(op.width), "start": _pt(op.start),
             "end": _pt(op.end)}
        if op.mid is not None:
            d["mid"] = _pt(op.mid)
        if op.chamfer_cut:
            d["chamfer_cut"] = True
        return d
    if isinstance(op, Via):
        d = {"kind": "via", "net": op.net, "at": _pt(op.at), "drill": _r(op.drill), "size": _r(op.size)}
        if op.layers:
            d["layers"] = [l.value for l in op.layers]
        return d
    if isinstance(op, Pour):
        return {"kind": "pour", "net": op.net, "layer": op.layer.value, "points": [_pt(p) for p in op.points],
                "stroke": _r(op.stroke), "fitted": op.fitted}
    if isinstance(op, Zone):
        return {"kind": "zone", "net": op.net, "layer": op.layer.value, "points": [_pt(p) for p in op.points],
                "clearance": _r(op.clearance), "min_thickness": _r(op.min_thickness), "solid_pads": op.solid_pads,
                "npth_clearance": _r(op.npth_clearance)}
    if isinstance(op, Text):
        return {"kind": "text", "text": op.text, "at": _pt(op.at), "face": op.face.value, "size": _r(op.size),
                "thickness": _r(op.thickness), "rotation": _r(op.rotation), "hjust": op.hjust, "vjust": op.vjust,
                "knockout": op.knockout, "mirrored": op.mirrored, "net": op.net, "layer": op.layer}
    raise NoteError("no note form for %s" % type(op).__name__)


def op_from_json(d: dict):
    kind = d["kind"]
    if kind == "track":
        return Track(d["net"], CopperLayer.of(d["layer"]), d["width"], _loc(d["start"]), _loc(d["end"]),
                     d.get("chamfer_cut", False), _loc(d["mid"]) if "mid" in d else None)
    if kind == "via":
        return Via(d["net"], _loc(d["at"]), d["drill"], d["size"], tuple(CopperLayer.of(x) for x in d.get("layers", ())))
    if kind == "pour":
        return Pour(d["net"], CopperLayer.of(d["layer"]), tuple((p[0], p[1]) for p in d["points"]), d["stroke"], d["fitted"])
    if kind == "zone":
        return Zone(d["net"], CopperLayer.of(d["layer"]), tuple((p[0], p[1]) for p in d["points"]), d["clearance"],
                    d["min_thickness"], d["solid_pads"], d["npth_clearance"])
    if kind == "text":
        return Text(d["text"], _loc(d["at"]), Face(d["face"]), d["size"], d["thickness"], d["rotation"], d["hjust"],
                    d["vjust"], d["knockout"], d["mirrored"], d["net"], None, d["layer"])
    raise NoteError("unknown op kind %r" % kind)


def keepout_to_json(k) -> dict:
    return {"name": k.name, "polygon": [_pt(p) for p in k.poly], "layers": None if k.layers is None else [l.value for l in k.layers],
            "excludes": list(k.excludes), "allow": sorted(k.allow), "why": k.why}


def keepout_from_json(d: dict):
    from .layout import PlacedKeepout
    layers = None if d["layers"] is None else tuple(CopperLayer.of(x) for x in d["layers"])
    return PlacedKeepout(d["name"], tuple((p[0], p[1]) for p in d["polygon"]), Location(0.0, 0.0), 0.0, tuple(d["excludes"]),
                         layers, frozenset(d["allow"]), frozenset(), d["why"], None, frozenset(), frozenset())


def base_digest(places) -> str:
    """The default places of the members, as a digest the notes of one cell share."""
    rows = [(inst, _r(p.location.x, 3), _r(p.location.y, 3), _r(p.rotation, 3) % 360.0, p.face.value)
            for inst, p in sorted(places, key=lambda t: t[0])]
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()[:16]


def document(ident: str, choices: dict, members, ops, keepouts, order: int = 0) -> dict:
    """The note's document. `members` is [(inst, pose in this arrangement, pose in the default)], all in the fragment's frame;
    `order` is where the module run laid the arrangement (the stamping board scans in that order)."""
    return {"v": VERSION, "id": ident, "order": order, "choices": dict(choices), "base": base_digest([(i, d) for i, _, d in members]),
            "members": [{"inst": i, "x": _r(p.location.x, 4), "y": _r(p.location.y, 4), "rotation": _r(p.rotation, 4),
                         "face": p.face.value, "from": pose_json(d)} for i, p, d in members],
            "ops": [op_to_json(o) for o in ops], "keepouts": [keepout_to_json(k) for k in keepouts]}


def encode(doc: dict, chars: int) -> list:
    """The texts that carry `doc`: one, or numbered ones (`placemat arrangement 2/3 <key> <chunk>`) of `chars` characters of
    escaped json each."""
    body = quote(json.dumps(doc, separators=(",", ":"), sort_keys=True), safe=_SAFE)
    if len(body) <= chars:
        return [ARRANGEMENT_PREFIX + body]
    key = hashlib.sha256(body.encode()).hexdigest()[:8]
    chunks = [body[k:k + chars] for k in range(0, len(body), chars)]
    return ["%s%d/%d %s %s" % (ARRANGEMENT_PREFIX, n, len(chunks), key, c) for n, c in enumerate(chunks, 1)]


def _parse(body: str):
    try:
        return json.loads(unquote(body))
    except ValueError:
        return None


def read_notes(texts) -> tuple:
    """(documents, problems) of a cell's arrangement texts, in no order: numbered texts joined, each document parsed and its
    version checked. A problem is `{"reason": "text" | "version", "ids": [...]}` and its arrangement is not among the documents."""
    docs, problems, parts = [], [], {}
    for t in texts:
        if not t.startswith(ARRANGEMENT_PREFIX):
            continue
        rest = t[len(ARRANGEMENT_PREFIX):]
        head = rest.split(" ", 2)
        if len(head) == 3 and "/" in head[0] and head[0].replace("/", "").isdigit():
            n, of = (int(x) for x in head[0].split("/"))
            parts.setdefault((head[1], of), {})[n] = head[2]
        else:
            parts.setdefault(None, []).append(rest)
    whole = [(None, body) for body in parts.pop(None, [])]
    for (key, of), got in parts.items():
        if sorted(got) != list(range(1, of + 1)):
            problems.append({"reason": "text", "ids": []})
            continue
        whole.append((key, "".join(got[n] for n in range(1, of + 1))))
    for _, body in whole:
        d = _parse(body)
        if not isinstance(d, dict) or "id" not in d:
            problems.append({"reason": "text", "ids": []})
        elif d.get("v") != VERSION:
            problems.append({"reason": "version", "ids": [d["id"]]})
        else:
            docs.append(d)
    return docs, problems
