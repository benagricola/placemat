"""The board builder's facts: the state of each fact the board carries, the edits that write a batch of them to their homes (the
`.zen`, `fab-profile.json`, `placemat.toml`), the confirmation, and the read-back after the board is regenerated.

The state is read from the same functions `placemat facts` uses (`facts.facts_of` through the worker's record,
`facts.unconfirmed_reasons`), so the page and the command cannot disagree."""
from __future__ import annotations

from pathlib import Path

from . import script_edit as se
from .builder import BUILDER, BuilderRefused, _positive
from .suggestions import Edit

VIA_KINDS = ("micro", "blind", "buried")
TIERS = ("yes", "no", "if-needed")
FAB_MIN_KEYS = ("track_mm", "clearance_mm", "drill_mm", "annular_mm", "via_size_mm")
LAYER_ROLES = ("signal", "power", "mixed", "ground")
FAB_PROFILE = "fab-profile.json"


def facts_document(d: dict):
    """The `FactsDocument` a worker's facts record (`facts_record`) describes."""
    from .facts import FactsDocument
    return FactsDocument(d["layers"], d["pairs"], d["via_types"], d["fab_min"], d["rise_c"], tuple(d.get("plane_mismatches", ())),
                         tuple(d.get("via_named", ())))


def facts_record(doc) -> dict:
    """A `FactsDocument` as the JSON the worker returns and the model reads."""
    return {"layers": doc.layers, "pairs": doc.pairs, "via_types": doc.via_types, "fab_min": doc.fab_min, "rise_c": doc.rise_c,
            "plane_mismatches": list(doc.plane_mismatches), "via_named": list(doc.via_named), "digest": doc.digest()}


def pair_candidates(nets) -> list:
    """Pairs the net names suggest, by the router's own rule (pairs.pair_key): `{"base", "positive", "negative", "style"}`, each
    base with both halves present. A suggestion from a name, not a decision."""
    from .pairs import pair_key
    halves: dict = {}
    for n in sorted(nets):
        k = pair_key(n)
        if k is None:
            continue
        base, positive, style = k
        halves.setdefault((base, style), {})[positive] = n
    out = []
    for (base, style), h in sorted(halves.items()):
        if True in h and False in h:
            out.append({"base": base, "positive": h[True], "negative": h[False], "style": style})
    return out


def _layer_of_mismatch(text: str) -> str:
    return text.split(" ", 1)[0]


def facts_model(record: dict, *, zen: dict, fab: dict, rise: dict, confirmed_digest: str = "", confirmed_doc: dict | None = None,
                acks: dict | None = None) -> dict:
    """The facts panel's state: a row for each fact with its state (decided, undecided, flagged, changed), the reasons
    `unconfirmed_reasons` gives, and the gate. `record` is `facts_record`; `zen` says what the board's `.zen` holds (`file`); `fab`
    the profile in force (`file`); `rise` whether `[check] rise_c` is set (`set`, `file`); `confirmed_doc` the record last
    confirmed, where it is known; `acks` what the page has acknowledged (`no_pairs`, and `plane:<layer>` for each flag)."""
    from .facts import unconfirmed_reasons
    from .finding_text import facts_reason_text
    acks = acks or {}
    doc = facts_document(record)
    reasons = unconfirmed_reasons(doc, confirmed_digest)
    mism = {_layer_of_mismatch(m): m for m in record.get("plane_mismatches", ())}
    rows = []
    declared = zen.get("stackup", "literal") != "none"      # a stackup the .zen does not declare is the generator's default: nobody decided it
    for name, info in record["layers"].items():
        state = "undecided" if info.get("copper_mm") is None or not declared else "decided"
        row = {"id": "layer:" + name, "fact": "layer", "label": name, "state": state, "value": dict(info), "home": zen.get("file", ""),
               "default": not declared}
        if name in mism:
            row.update(flag=mism[name], acknowledged=bool(acks.get("plane:" + name)))
            if state == "decided" and not acks.get("plane:" + name):
                row["state"] = "flagged"
        rows.append(row)
    pairs = record["pairs"]
    no_pairs = bool(acks.get("no_pairs"))
    rows.append({"id": "pairs", "fact": "pairs", "label": "Differential pairs", "state": "decided" if pairs or no_pairs else "undecided",
                 "value": {"classes": pairs, "none": no_pairs and not pairs}, "home": zen.get("file", "")})
    for kind in VIA_KINDS:
        named = kind in record.get("via_named", ())
        rows.append({"id": "via:" + kind, "fact": "via", "label": "%s vias" % kind, "state": "decided" if named else "undecided",
                     "value": {"tier": record["via_types"][kind] if named else None}, "home": fab.get("file") or FAB_PROFILE})
    rows.append({"id": "min", "fact": "min", "label": "Fab minimums", "state": "decided" if record["fab_min"] else "undecided",
                 "value": dict(record["fab_min"]), "home": fab.get("file") or FAB_PROFILE})
    rows.append({"id": "rise", "fact": "rise", "label": "The rise", "state": "decided" if rise.get("set") else "undecided",
                 "value": {"rise_c": record["rise_c"]}, "home": rise.get("file") or "placemat.toml"})
    changed_known = False
    if confirmed_digest and confirmed_digest != record["digest"] and confirmed_doc:
        changed_known = True
        was = confirmed_doc
        for r in rows:
            if r["state"] not in ("decided", "flagged"):
                continue
            if r["fact"] == "layer":
                differs = was["layers"].get(r["label"]) != record["layers"][r["label"]]
            elif r["fact"] == "pairs":
                differs = was["pairs"] != record["pairs"]
            elif r["fact"] == "via":
                differs = was["via_types"][r["id"][4:]] != record["via_types"][r["id"][4:]]
            elif r["fact"] == "min":
                differs = was["fab_min"] != record["fab_min"]
            else:
                differs = was["rise_c"] != record["rise_c"]
            if differs:
                r["state"] = "changed"
    counts = {s: sum(1 for r in rows if r["state"] == s) for s in ("decided", "undecided", "flagged", "changed")}
    holds = [r["id"] for r in rows if r["state"] in ("undecided", "flagged", "changed")]
    if confirmed_digest and confirmed_digest != record["digest"] and not changed_known:
        counts["changed"] = 1       # the digest differs and the confirmed record is not known: which fact moved is not recorded
        holds.append("changed")
    if reasons and not holds:
        holds.append("confirmation")        # everything is decided but the digest is not recorded yet
    return {"rows": rows, "counts": counts, "digest": record["digest"], "confirmed": bool(confirmed_digest) and not reasons,
            "reasons": [dict(r, text=facts_reason_text(r)) for r in reasons], "changed_known": changed_known,
            "gate": {"open": not reasons, "holds": holds}, "pairs": pairs}


def can_confirm(model: dict) -> list:
    """What stops the Confirm button: an undecided row, a flag not acknowledged. Empty means it may be pressed."""
    return ["%s is undecided" % r["label"] for r in model["rows"] if r["state"] == "undecided"] + \
           ["%s: %s (acknowledge it, or change the layer's role)" % (r["label"], r["flag"]) for r in model["rows"]
            if r["state"] == "flagged"]


def weight_row(row: dict) -> dict:
    """A stackup row of the form with its thickness in mm: the form gives `oz`, `thickness_um` or `thickness_mm`."""
    from .zen_edit import mm_to_oz, oz_to_mm
    out = dict(row)
    if row.get("kind") == "copper":
        if row.get("oz") not in (None, ""):
            if float(row["oz"]) <= 0:
                raise BuilderRefused("a copper weight is above 0 oz")
            out["thickness_mm"] = oz_to_mm(float(row["oz"]))
            out["oz"] = float(row["oz"])
        else:
            out.pop("oz", None)
            if row.get("thickness_um") not in (None, ""):
                out["thickness_mm"] = round(float(row["thickness_um"]) / 1000.0, 6)
        if out.get("thickness_mm") is not None:
            std = mm_to_oz(out["thickness_mm"])
            if std is not None and "oz" not in out:
                out["oz"] = std          # a thickness that is a standard weight is shown (and commented) as that weight
    out.pop("thickness_um", None)
    return out


def fab_plan(board_dir, root, sets: list, *, read=None) -> dict:
    """Where the values for `fab-profile.json` are written and how. `sets` is [(path, value)]. The profile `project.fab_profile`
    would use is the first one from the board's folder up. With none, the values are written to a new file at the project `root`.
    A profile found above the board is left alone and, only when a value differs, a full copy with the values set is written
    beside the board (the lookup takes one file whole, so a partial file would drop the rest). A profile beside the board is
    edited in place. Returns `{"mode": "none"|"edit"|"create_root"|"copy_beside", "file", "from", "text" (what the file holds
    after), "says"}`."""
    from . import json_edit
    read = read or (lambda p: Path(p).read_text(encoding="utf-8"))
    board_dir, root = Path(board_dir).resolve(), Path(root).resolve()
    found = next((d / FAB_PROFILE for d in (board_dir, *board_dir.parents) if (d / FAB_PROFILE).is_file()), None)
    if found is None:
        text = json_edit.set_values("{}\n", sets) if sets else ""
        return {"mode": "create_root" if sets else "none", "file": str(root / FAB_PROFILE), "from": None, "text": text,
                "says": "there is no %s: this board's choices are written to %s, the project's default" % (FAB_PROFILE, root / FAB_PROFILE)}
    text = read(found)
    changed = json_edit.set_values(text, sets) if sets else text
    if changed == text:
        return {"mode": "none", "file": str(found), "from": str(found), "text": text, "says": ""}
    if found.parent == board_dir:
        return {"mode": "edit", "file": str(found), "from": str(found), "text": changed, "says": ""}
    return {"mode": "copy_beside", "file": str(board_dir / FAB_PROFILE), "from": str(found), "text": changed,
            "says": "this board gets its own %s beside it; the project's %s is left as it is" % (FAB_PROFILE, found)}


def toml_file(board_dir) -> Path:
    """The placemat.toml facts and the rise are written to: the nearest one above the board; a new one beside the board only
    where none exists (as `placemat facts --confirm` chooses it)."""
    from .settings import _files
    found = _files(board_dir)
    return found[-1] if found else Path(board_dir) / "placemat.toml"


def facts_edits(request: dict, *, zen_file: str, board_name: str, board_dir, root, read=None) -> dict:
    """The edits for a batch of facts: `request` has any of `stackup` ({"copper_layers", "rows"}), `pairs` ({"classes"}), `via`
    ({kind: tier, "default_drill_mm", "default_size_mm"}), `min` ({key: mm}) and `rise_c`. Returns `{"edits", "digests", "label",
    "says"}`: each file written is one edit, so one `apply_edits` writes them all, with one log entry."""
    read = read or (lambda p: Path(p).read_text(encoding="utf-8"))
    edits, digests, says, labels = [], {}, [], []

    def digest_of(path):
        try:
            return se.digest(read(path))
        except OSError:
            return ""
    if "stackup" in request:
        s = request["stackup"]
        rows = [weight_row(r) for r in s["rows"]]
        edits.append(Edit("zen_stackup", None, {"board": board_name, "layers": rows, "copper_layers": s.get("copper_layers")}, None, {},
                          zen_file))
        digests[zen_file] = digest_of(zen_file)
        labels.append("stackup")
    if "pairs" in request:
        edits.append(Edit("zen_netclasses", None, {"board": board_name, "classes": request["pairs"]["classes"]}, None, {}, zen_file))
        digests[zen_file] = digest_of(zen_file)
        labels.append("pair classes" if request["pairs"]["classes"] else "no pair classes")
    sets = []
    if "via" in request:
        v = request["via"]
        for kind in VIA_KINDS:
            if kind in v:
                if v[kind] not in TIERS:
                    raise BuilderRefused("a via type is yes, no or if-needed, not %r" % (v[kind],))
                sets.append((["via", kind], v[kind]))
        for key in ("default_drill_mm", "default_size_mm"):
            if v.get(key) is not None:
                sets.append((["via", key], _positive(v, key)))
        labels.append("via types")
    if "min" in request:
        for key in request["min"]:
            if key not in FAB_MIN_KEYS:
                raise BuilderRefused("%r is not a fab minimum (%s)" % (key, ", ".join(FAB_MIN_KEYS)))
            sets.append((["min", key], _positive(request["min"], key)))
        labels.append("fab minimums")
    if sets:
        plan = fab_plan(board_dir, root, sets, read=read)
        if plan["mode"] in ("create_root", "copy_beside"):
            edits.append(Edit("create_file", None, {"text": plan["text"]}, None, {}, plan["file"]))
            digests[plan["file"]] = ""
        elif plan["mode"] == "edit":
            edits.append(Edit("json_set", None, {"sets": [{"path": p, "value": v} for p, v in sets]}, None, {}, plan["file"]))
            digests[plan["file"]] = digest_of(plan["file"])
        if plan["says"] and plan["mode"] != "none":
            says.append(plan["says"])
    if "rise_c" in request:
        v = request["rise_c"]
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
            raise BuilderRefused("the rise is a number of degrees C above 0")
        toml = toml_file(board_dir)
        comment = "the temperature rise the current checks allow, chosen in %s" % BUILDER
        try:
            text = read(toml)
        except OSError:
            text = None
        if text is None:
            edits.append(Edit("create_file", None, {"text": se.toml_set("", ["check"], "rise_c", float(v), comment)}, None, {}, str(toml)))
            digests[str(toml)] = ""
        else:
            edits.append(Edit("toml_set", None, {"table": ["check"], "key": "rise_c", "comment": comment}, float(v), {}, str(toml)))
            digests[str(toml)] = digest_of(toml)
        labels.append("the rise")
    if not edits:
        raise BuilderRefused("nothing to write: every fact asked for is as it is")
    return {"edits": edits, "digests": digests, "label": "Facts: " + ", ".join(labels), "says": says}


def confirm_edit(script, digest: str, board_dir) -> dict:
    """The edit that records the facts' digest for `script`, as `placemat facts --confirm` records it (the same key, the same
    file, `facts.confirmed_text`)."""
    from . import facts as facts_mod
    toml = toml_file(board_dir)
    key = facts_mod.script_key(script, toml)
    try:
        before = Path(toml).read_text(encoding="utf-8")
    except OSError:
        before = None
    e = Edit("confirm_facts", None, {"digest": digest, "key": key}, None, {}, str(toml))
    return {"edits": [e], "digests": {str(toml): se.digest(before) if before is not None else ""}, "label": "Facts confirmed",
            "file": str(toml), "key": key}


def readback(asked: dict, record: dict) -> list:
    """Where the facts read back from the regenerated board differ from what a batch asked for: `{"fact", "name", "asked",
    "got"}`. A fact the generator ignored shows here, and the page offers an undo."""
    out = []
    if "stackup" in asked:
        rows = [weight_row(r) for r in asked["stackup"]["rows"] if r["kind"] == "copper"]
        got = list(record["layers"].items())
        if len(rows) != len(got):
            out.append({"fact": "layers", "name": "copper layers", "asked": len(rows), "got": len(got)})
        for r, (name, info) in zip(rows, got):
            role = "power" if r["role"] in ("ground", "power") else r["role"]      # KiCad has no ground layer type: it is written power
            if info["role"] != role:
                out.append({"fact": "layer", "name": name, "asked": {"role": r["role"]}, "got": {"role": info["role"]}})
            if info.get("copper_mm") is None or abs(info["copper_mm"] - r["thickness_mm"]) > 1e-6:
                out.append({"fact": "layer", "name": name, "asked": {"copper_mm": r["thickness_mm"]}, "got": {"copper_mm": info.get("copper_mm")}})
    if "pairs" in asked:
        want = {c["name"]: sorted(c["nets"]) for c in asked["pairs"]["classes"]}
        if want != record["pairs"]:
            out.append({"fact": "pairs", "name": "pair classes", "asked": want, "got": record["pairs"]})
    if "via" in asked:
        for kind in VIA_KINDS:
            if kind in asked["via"] and record["via_types"].get(kind) != asked["via"][kind]:
                out.append({"fact": "via", "name": kind, "asked": asked["via"][kind], "got": record["via_types"].get(kind)})
    if "min" in asked:
        for key, val in asked["min"].items():
            if abs(record["fab_min"].get(key, -1) - val) > 1e-9:
                out.append({"fact": "min", "name": key, "asked": val, "got": record["fab_min"].get(key)})
    if "rise_c" in asked and abs(record["rise_c"] - asked["rise_c"]) > 1e-9:
        out.append({"fact": "rise", "name": "rise_c", "asked": asked["rise_c"], "got": record["rise_c"]})
    return out
