"""A step's notes as data, and the sentence rendered from each.

A step says what happened to it as a list of notes: `{"kind": ..., **facts}`, the facts JSON values the producing site measured (numbers,
names, a refusal as `Refusal.to_json()`, a `where` as the dict finding_text.where_text reads). This module is the one place that turns
them into words, as finding_text.py does for findings: the console, `placemat watch`, the run records' text and the studio show the
same sentences, and nothing reads a sentence for data.

`Step.note` is the rendered text (`render_all`): each note's sentence joined with "; ", the rank, the script's priority and "required"
in one clause. Units are in a field's name (`mm`, `area_mm2`); a side is its lower-case word, a point is [x, y] in board
millimetres."""
from __future__ import annotations

from . import finding_text

RENDER: dict = {}
TIER = ("rank", "priority", "required")         # one clause: "rank 3/9 (...) (script: high), required"


def record(kind: str, **facts) -> dict:
    """A note of this kind. A fact that is None is left out, so a note that has none of it is not different from one that never could."""
    return {"kind": kind, **{k: v for k, v in facts.items() if v is not None}}


def renders(kind: str):
    def register(fn):
        RENDER[kind] = fn
        return fn
    return register


def _refusal(d) -> str:
    from .refusals import Refusal
    return str(Refusal.from_json(d))


def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return "%dth" % n
    return "%d%s" % (n, {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))


def _why(n: dict, sep: str = ": ") -> str:
    return (sep + _refusal(n["why"])) if n.get("why") else ""


def _list(names) -> str:
    return ", ".join(names)


# ------------------------------------------------------------------ how an item was reached
@renders("rank")
def _rank(n):
    return "rank %d/%d (%.1f mm2, %s of %d; %d pins, %s)" % (
        n["rank"], n["of"], n["area_mm2"], ordinal(n["area_rank"]), n["of"], n["pins"], ordinal(n["pins_rank"]))


@renders("priority")
def _priority(n):
    return " (script: %s)" % n["value"]


@renders("required")
def _required(n):
    return "required"


@renders("next_largest")
def _next_largest(n):
    return "next: largest (%.0f mm2)" % n["area_mm2"]


@renders("one_freedom")
def _one_freedom(n):
    return "one freedom: before the items of its tier searched in two"


@renders("room")
def _room(n):
    spots = ("room %.0f spots" % n["spots"]) if "spots" in n else "room: the whole board"
    cut = (", %.0f mm2 cut by limits" % n["cut_mm2"]) if "cut_mm2" in n else ""
    return "%s (%s%s, counted at %.1f mm), band %d" % (spots, n["form"], cut, n["pitch_mm"], n["level"])


@renders("waited_for")
def _waited_for(n):
    return "waited for %s, the item it is linked to with more placed connections" % n["partner"]


@renders("placed_before")
def _placed_before(n):
    return "placed before %s: %s stood in its way, and now stands off it" % (n["other"], n["other"])


@renders("no_faces_declared")
def _no_faces(n):
    return "no faces declared: turned as if its outward side were local +Y"


@renders("seeded")
def _seeded(n):
    return "seeded on %s" % _list(n["nets"])


@renders("seeded_by_solve")
def _seeded_by_solve(n):
    return "seeded by the global solve"


@renders("seeded_no_spot")
def _seeded_no_spot(n):
    return "%s, but no legal spot within %.1f mm (%s)" % (
        ("seeded on %s" % _list(n["nets"])) if n.get("nets") else "seeded", n["radius_mm"], finding_text.blame_text(n["blame"]))


@renders("took_pocket")
def _took_pocket(n):
    return finding_text.pocket_took_text(n["pocket"])


POCKET_WHY = "nothing it connects to is placed"


@renders("pocket")
def _pocket(n):
    return "pocket %.1f x %.1f at (%.1f, %.1f): %s" % (n["w_mm"], n["h_mm"], n["at"][0], n["at"][1], POCKET_WHY)


@renders("pocket_scan")
def _pocket_scan(n):
    return "%s; no pocket fits it (%d tried), found by a scan of the whole face" % (POCKET_WHY, n["tried"])


@renders("pocket_other_face")
def _pocket_other_face(n):
    return "on the %s face, where the %s has no pocket it fits" % (n["face"], n["wanted"])


@renders("back_face")
def _back_face(n):
    if n.get("front_blame") is not None:
        return "on the back face: the front has no legal spot (%s)" % finding_text.blame_text(n["front_blame"])
    if n.get("front_beaten"):
        return "on the back face: %.2f and %.2f for the back face; the front could not beat the best so far" % (n["back"], n["cost"])
    return "on the back face: %.2f and %.2f for the back face against %.2f on the front" % (n["back"], n["cost"], n["front"])


@renders("arrangement")
def _arrangement(n):
    if "id" not in n:                               # nothing stood: the arrangements tried, in order
        ids = [t["id"] for t in n["tried"]]
        return "no arrangement has a legal spot: tried %s" % (ids[0] if len(ids) == 1 else "%s and %s" % (_list(ids[:-1]), ids[-1]))
    if n.get("default_blame") is not None:
        return "arrangement %s: the default module has no legal spot (%s)" % (n["id"], finding_text.blame_text(n["default_blame"]))
    if n.get("score") is None:
        return "arrangement %s" % n["id"]
    said = "arrangement %s: %.2f and %.2f for it" % (n["id"], n["score"], n.get("cost", 0.0))
    if n.get("within") is not None:
        w = n["within"]
        return said + "; %s %.2f mm better, within the %.2f mm margin; the default stands" % (w["id"], w["by"], w["margin"])
    if n.get("default_score") is not None and n["id"] != "default":
        return said + " against %.2f as the default module stands" % n["default_score"]
    others = [t["id"] for t in n.get("tried", ()) if t["id"] != n["id"] and t["legal"]]
    return said + (", the lowest of it and %s" % _list(others) if others else "")


@renders("lookahead_dropped")
def _lookahead_dropped(n):
    return "no spot left %s room, so the look-ahead was dropped" % _list(n["partners"])


@renders("solve_hint_dropped")
def _solve_hint_dropped(n):
    return "the global solve's hint had no legal spot within %.1f mm, so it was dropped" % n["radius_mm"]


@renders("room_kept")
def _room_kept(n):
    return "room kept for %s" % _list(n["for"])


# ------------------------------------------------------------------ where along its freedom
@renders("where")
def _where(n):
    return finding_text.where_text(n["where"])


@renders("slid")
def _slid(n):
    return "slid %.2f %s from its slot%s" % (n["mm"], n.get("units", "mm"), _why(n))


@renders("stopped_short")
def _stopped_short(n):
    return "stopped %.2f %s short of the %s end by: %s" % (n["mm"], n.get("units", "mm"), n["toward"], _refusal(n["why"]) if n.get("why") else "")


@renders("turned")
def _turned(n):
    return "turned %g of %d bearings tried about its point%s" % (n["rot"], n["of"], (", cost %.2f" % n["cost"]) if n.get("cost") is not None else "")


@renders("refused_count")
def _refused_count(n):
    return "%d refused: %s" % (n["n"], _refusal(n["why"]))


@renders("locked_order")
def _locked_order(n):
    return "locked order"


@renders("explore_before")
def _explore_before(n):
    return "explore: before %s" % n["other"]


FOR_SCORE = "for a better link score"


@renders("moved_off_hint")
def _moved_off_hint(n):
    return "moved %.2f mm off the hint%s%s" % (n["mm"], _why(n), (" " + FOR_SCORE) if n.get("for_score") else "")


@renders("block")
def _block(n):
    return "block of %d laid out from the anchor's pads" % n["members"]


@renders("member_of")
def _member_of(n):
    return "in %s" % n["block"]


@renders("anchor_of")
def _anchor_of(n):
    return "anchor of %s" % n["block"]


@renders("pin_row_slide")
def _pin_row_slide(n):
    return "slid %.2f mm along the pin row from %s pin %s's axis" % (n["mm"], n["ref"], n["pin"])


@renders("in_front_of")
def _in_front_of(n):
    return "in front of %s pin%s %s" % (n["ref"], "s" if len(n["pins"]) > 1 else "", _list(n["pins"]))


@renders("rides")
def _rides(n):
    return "rides %s" % n["of"]


@renders("chose_pad")
def _chose_pad(n):
    return "%s is %d pads on %s: pad %s is the one on the point" % (n["net"], n["count"], n["ref"], n["pad"])


@renders("refused")
def _refused(n):
    return _refusal(n["why"])


# ------------------------------------------------------------------ lock
@renders("lock_held")
def _lock_held(n):
    return "held by lock"


@renders("lock_drifted")
def _lock_drifted(n):
    return "lock: drifted %.2f mm from its locked spot%s" % (n["mm"], _why(n))


_RELEASED = {
    "declaration_changed": lambda r: "its declaration changed since it was accepted",
    "anchor_pending": lambda r: "its anchor %s is not placed before it" % r["ref"],
    "anchor_face": lambda r: "its anchor %s is on the other face now" % r["ref"],
    "anchor_pad_gone": lambda r: "its anchor pad %s.%s is gone" % (r["ref"], r["pad"]),
    "no_spot_near": lambda r: "no legal spot within %.1f mm of its locked spot" % r["radius_mm"],
    "no_spot_round": lambda r: "no legal spot round its locked spot",
    "arrangement_gone": lambda r: "the module no longer offers arrangement %s" % r["id"],
}


@renders("lock_released")
def _lock_released(n):
    return "lock: released - " + _RELEASED[n["reason"]["form"]](n["reason"])


# ------------------------------------------------------------------ pushes and exposure
@renders("push")
def _push(n):
    return "push from %s: %.2g at %.1f mm (limit %.2g)" % (n["source"], n["value"], n["at_mm"], n["limit"])


@renders("exposure")
def _exposure(n):
    return "%s at %s: %.2g %s of %.3g %s limit, nearest source %s at %.1f mm" % (
        n["quantity"], n["sensitive"], n["total"], n["unit"], n["limit"], n["unit"], n["nearest"], n["at_mm"])


# ------------------------------------------------------------------ what the pass over the board did
@renders("cleanup")
def _cleanup(n):
    said = []
    if n.get("swapped_with"):
        said.append("swapped with %s" % _list(n["swapped_with"]))
    if n.get("moved_mm") is not None:
        said.append("moved %.2f mm" % n["moved_mm"])
    return "cleanup: " + "; ".join(said)


@renders("stamped_regions")
def _stamped_regions(n):
    return "its stamped regions keep parts off %.1f mm2 of board beyond its own parts" % n["area_mm2"]


@renders("vias")
def _vias(n):
    return "vias: " + finding_text.vias_note(n["facts"])


@renders("split")
def _split(n):
    return "split: " + finding_text.split_note(n["facts"])


@renders("drops")
def _drops(n):
    if n["fields"]:
        return "drops %s: %s" % (n["mode"], ", ".join("%d of %d in %s.%s" % (f["kept"], f["of"], f["ref"], f["pad"]) for f in n["fields"]))
    return "drops %s: no via field of a plane net" % n["mode"]


_STANDING = {"own_plane": "its own plane", "other_plane": "another net's plane", "no_plane": "no plane"}


def _ends(span) -> str:
    return "%s-%s" % (span[0], span[-1])


@renders("flip_via")
def _flip_via(n):
    why = n["why"]
    said = ("a %s layer onto a %s one" % (why["from"], why["to"])) if why["form"] == "types" else \
        "%s onto %s" % (_STANDING[why["from"]], _STANDING[why["to"]])
    return ("flipped, its %s via %s becomes %s: its inner end moves from %s to %s (%s), while the cell's own copper there stays" % (
        n["net"], _ends(n["span"]), _ends(n["flipped"]), n["from_layer"], n["to_layer"], said))


@renders("unplaced")
def _unplaced(n):
    return "UNPLACED"


@renders("search_budget")
def _search_budget(n):
    return finding_text.budget_text(n) + ", and the best spot found is taken"


# ------------------------------------------------------------------ regions and copper
@renders("cut")
def _cut(n):
    return "cut at %.2f, %.2f facing %.0f" % (n["at"][0], n["at"][1], n["turn"])


@renders("kept_clear")
def _kept_clear(n):
    return "kept clear at %.2f, %.2f" % (n["at"][0], n["at"][1])


@renders("points_off_board")
def _points_off_board(n):
    return "%d of its %d points are off the board" % (n["outside"], n["of"])


@renders("ops")
def _ops(n):
    return "%d op(s)" % n["n"]


@renders("in_pad_vias")
def _in_pad_vias(n):
    return "in the pad: filled or plugged at the fab"


@renders("lanes")
def _lanes(n):
    return "%d lane%s kept for pins %s" % (n["n"], "" if n["n"] == 1 else "s", _list(n["pins"]))


@renders("lanes_blocked")
def _lanes_blocked(n):
    return "%d blocked" % n["n"]


@renders("fanout")
def _fanout(n):
    sides = n["sides"]
    return "%s side%s kept for its pins, %.2f mm deep" % (_list(sides) or "no", "" if len(sides) == 1 else "s", n["depth_mm"])


@renders("faces")
def _faces(n):
    return " ".join("%s=%s" % (k, v) for k, v in n["sides"].items())


@renders("bridge")
def _bridge(n):
    return "%s passes under %s at (%.2f, %.2f): %s" % (n["net"], n["under"], n["at"][0], n["at"][1], n["why"].replace("_", " "))


@renders("label_at")
def _label_at(n):
    return "%s%s of %s" % (n["side"], (" " + n["word"]) if n.get("word") else "", n["item"])


@renders("label_off_board")
def _label_off_board(n):
    from .refusals import edge_phrase
    return "moved from %s: it was %s" % (n["was"], edge_phrase(n["fault"]["verdict"], n["fault"]["margin_mm"]))


@renders("sits_on")
def _sits_on(n):
    return "sits on " + _list(n["hits"])


@renders("reserved")
def _reserved(n):
    return "reserved"


@renders("label_moved")
def _label_moved(n):
    return "moved from %s to %s: %s was there" % (n["from"], n["to"], _list(n["by"]))


# ------------------------------------------------------------------ rendering
def render(n: dict) -> str:
    return RENDER[n["kind"]](n)


def render_all(notes, unplaced=None) -> str:
    """The notes as one line: each sentence, "; "-separated, with the tier's rank, priority and "required" as one clause. A step
    that is unplaced says "UNPLACED: " and its reasons (`unplaced`, rendered by `unplaced_text`) where its note has the kind."""
    parts, last = [], None
    for n in notes:
        kind = n["kind"]
        text = ("UNPLACED: " + unplaced_text(unplaced) if unplaced else "UNPLACED") if kind == "unplaced" else render(n)
        if parts and kind in TIER[1:] and last in TIER:
            parts[-1] += text if kind == "priority" else ", " + text
        else:
            parts.append(text)
        last = kind
    return "; ".join(parts)


_FORMS = {
    "no_pocket": lambda r: "no pocket fits",
    "time_limit": lambda r: "gave up at its time limit (--step-limit)",
    "riders_alone": lambda r: finding_text.riders_alone_note(r),
    "turns": lambda r: finding_text.turns_text(r["turns"]),
    "rides": lambda r: finding_text.rides_note(r),
    "pocket": lambda r: finding_text.pocket_note(r),
    "room_lost": lambda r: finding_text.room_lost_text(r["room_lost"]).lstrip("; "),
    "budget": lambda r: finding_text.budget_text(r["budget"]),
    "arrangement_missing": lambda r: "arrangements= names %s; the cell offers %s" % (", ".join(r["asked"]), ", ".join(r["offered"])),
}


def unplaced_text(reasons) -> str:
    """The reasons an item has no place, "; "-separated: each a refusal (`Refusal.to_json()`, it has a "code") or a record with a
    "form" (and no "code") for what the finding's own facts state."""
    return "; ".join(_tagged(r) if "code" in r else _FORMS[r["form"]](r) for r in reasons or ())


def _tagged(r: dict) -> str:
    """A refusal record, said with the arrangement it came from when it carries one (a search over arrangements tags each)."""
    if "arrangement" not in r:
        return _refusal(r)
    r = dict(r)
    return "as %s: %s" % (r.pop("arrangement"), _refusal(r))
