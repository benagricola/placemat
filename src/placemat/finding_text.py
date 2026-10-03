"""The facts of each finding cause and the sentence rendered from them.

A finding is data: its cause (findings.FindingCause) and `facts`, a dict of JSON values the raising site measured. This
module is the one place that turns them into words: a renderer per cause, keyed by the enum member, written from the
sentence the finding has always had, so the console, the logs, `run.json`'s `text` and the studio show the same words.
Nothing else formats a finding's figures into a sentence, and nothing reads the sentence for data.

Units are in a field's name (`gap_mm`, `angle_deg`). A side is an Edge name ("NORTH"), a point is [x, y] in board
millimetres, a pad is [item, number], an item is the key a `place` declaration has. `FACTS_V` is a cause's schema version:
a reader that does not know it ignores the facts and shows the text, and the reuse record is made under a digest of all of
them, so a changed schema replays nothing."""
from __future__ import annotations

import hashlib

from .findings import FindingCause as C

RENDER: dict = {}
REQUIRED: dict = {}
FACTS_V: dict = {}                  # cause -> schema version; 1 unless it has been changed


def renders(cause, *required):
    """Register the renderer of `cause`, and the fields its facts must have."""
    def register(fn):
        RENDER[cause] = fn
        REQUIRED[cause] = tuple(required)
        return fn
    return register


def facts_version(cause) -> int:
    return FACTS_V.get(cause, 1)


def render(cause, facts: dict) -> str:
    missing = [k for k in REQUIRED[cause] if k not in facts]
    if missing:
        raise KeyError("%s facts lack %s" % (cause.value, ", ".join(missing)))
    return RENDER[cause](facts)


def schemas_digest() -> str:
    """A digest of every cause's schema version: what the reuse record's context holds."""
    return hashlib.sha256(";".join("%s=%d" % (c.value, facts_version(c)) for c in sorted(RENDER, key=lambda c: c.value))
                          .encode()).hexdigest()[:16]


def label_key(f: dict) -> str:
    """The key a label declaration has: its item and its text."""
    return "label %s %s" % (f["item"], f["text"])


def _list(names, empty: str = "") -> str:
    return ", ".join(names) or empty


# ------------------------------------------------------------------ link
@renders(C.LINK_OVER, "a", "b", "achieved_mm", "limit_mm", "why")
def _link_over(f):
    return "link %s.%s to %s.%s is %.2f mm, over its %.2f mm limit%s" % (
        f["a"]["ref"], f["a"]["pad"], f["b"]["ref"], f["b"]["pad"], f["achieved_mm"], f["limit_mm"],
        (": " + f["why"]) if f["why"] else "")


# ------------------------------------------------------------------ labels
@renders(C.LABEL_SITS_ON, "item", "text", "hits")
def _label_sits_on(f):
    return "%s: sits on %s" % (label_key(f), ", ".join(f["hits"]))


@renders(C.LABEL_NOT_DRAWN, "item", "text", "waiting")
def _label_not_drawn(f):
    return "%s: not drawn: %s found no place" % (label_key(f), f["waiting"])


# ------------------------------------------------------------------ copper
@renders(C.COPPER_KEEPOUT, "word", "net", "keepout", "why")
def _copper_keepout(f):
    return ("%s %s crosses keepout %r (%s): a %s goes exactly where it is put, so move it, "
            "reshape it, or name its net in the keepout's allow=" % (f["word"], f["net"], f["keepout"], f["why"], f["word"]))


@renders(C.COPPER_CROSS, "variant", "net_a", "net_b", "layer", "at")
def _copper_cross(f):
    left = "; %s is not drawn" % f["left_out"] if f.get("left_out") else ""
    if f["variant"] == "fixed":
        return "%s crosses FIXED %s on %s at (%.2f, %.2f) and may not bridge%s" % (
            f["net_a"], f["net_b"], f["layer"], f["at"][0], f["at"][1], left)
    return "%s and %s cross on %s at (%.2f, %.2f) and neither may bridge%s" % (
        f["net_a"], f["net_b"], f["layer"], f["at"][0], f["at"][1], left)


# ------------------------------------------------------------------ escapes and pairs
@renders(C.ESCAPE_CROSSED, "ref", "pins", "targets")
def _escape_crossed(f):
    (pa, pb), ((xa, na), (xb, nb)) = f["pins"], f["targets"]
    return "%s pins %s/%s: %s %s crosses %s %s" % (f["ref"], pa, pb, xa, na, xb, nb)


@renders(C.ESCAPE_CLOSED, "ref", "pin", "net", "joins", "by")
def _escape_closed(f):
    return "%s pin %s (%s): closed toward %s by %s" % (
        f["ref"], f["pin"], f["net"], _list(f["joins"], "what it joins"), _list(f["by"], "copper"))


@renders(C.ESCAPE_WALLED, "variant", "ref", "pin", "net", "by")
def _escape_walled(f):
    if f["variant"] == "handoff":
        return ("%s pin %s (%s): no other pad is on the net, so it leaves the board here, and it is walled off by %s"
                % (f["ref"], f["pin"], f["net"], _list(f["by"], "copper")))
    return "%s pin %s (%s): walled off by %s" % (f["ref"], f["pin"], f["net"], _list(f["by"], "copper"))


@renders(C.ESCAPE_LANE, "ref", "pin", "net", "blocked")
def _escape_lane(f):
    return "%s pin %s (%s): its lane is blocked by %s" % (f["ref"], f["pin"], f["net"], "; ".join(f["blocked"]))


@renders(C.PAIR_CROSSED, "pos", "neg", "parts")
def _pair_crossed(f):
    return ("%s/%s cross between %s: swap two interchangeable parts on the pair, or turn a part whose pinout is mirrored "
            "180 degrees" % (f["pos"], f["neg"], ", ".join(f["parts"])))


# ------------------------------------------------------------------ setup
@renders(C.SETUP_UNDECLARED, "item", "ref")
def _setup_undeclared(f):
    return "%s (%s): no declaration places it, so it stays where the generator put it" % (f["item"], f["ref"])


@renders(C.SETUP_LANE_UNUSED, "ref", "pin")
def _setup_lane_unused(f):
    return "%s pin %s: its lane is reserved and no track begins with it, so its room is kept for nothing" % (f["ref"], f["pin"])


@renders(C.SETUP_PITCH, "ref", "net_class", "clearance_mm", "track_mm", "pad", "past_pad", "lane_mm", "need_mm", "short",
         "fits_mm")
def _setup_pitch(f):
    return ("%s: net class %r (clearance %.2f mm, track %.2f mm) does not fit the pads' pitch: the lane out "
            "of pad %s past pad %s is %.3f mm for a %.2f mm clearance (%d lane(s) short), so the router "
            "cannot escape them; a clearance of %.2f mm or less fits"
            % (f["ref"], f["net_class"], f["clearance_mm"], f["track_mm"], f["pad"], f["past_pad"], f["lane_mm"],
               f["need_mm"], f["short"], f["fits_mm"]))


@renders(C.SETUP_WEB, "cutout", "gap_mm", "web_mm")
def _setup_web(f):
    return "web %.2f mm round %s is under the %.2f mm minimum" % (
        f["gap_mm"], "cutout %r" % f["cutout"] if f["cutout"] is not None else "an unnamed cutout", f["web_mm"])


@renders(C.SETUP_FRAME_REACH, "item", "from_mm", "to_mm", "axis", "frame_from_mm", "frame_to_mm")
def _setup_frame_reach(f):
    return "%s: reaches %.2f to %.2f mm, outside the frame's declared %s of %.2f to %.2f mm" % (
        f["item"], f["from_mm"], f["to_mm"], f["axis"], f["frame_from_mm"], f["frame_to_mm"])


@renders(C.SETUP_LAYER_LOST, "variant", "layers", "name")
def _setup_layer_lost(f):
    if f["variant"] == "keepout":
        return ("keepout %s declares %s, which this %d-layer board does not have: recorded in its name, and honoured by a "
                "board that has it" % (f["name"], ", ".join(f["layers"]), f["board_layers"]))
    return "%s from the %s cell declares %s, which this board does not have either" % (
        f["name"], f["cell"] or "board", ", ".join(f["layers"]))


@renders(C.SETUP_ACCEPT, "variant", "check", "subject")
def _setup_accept(f):
    if f["variant"] == "unmatched":
        return "accept %s %s: no verdict by that check and subject on this board" % (f["check"], f["subject"])
    return "accept %s %s: not needed: the check %s" % (
        f["check"], f["subject"], {"passes": "passes", "not_judged": "is not judged"}[f["why_not"]])


# ------------------------------------------------------------------ fab
@renders(C.FAB_MINIMUM, "net_class", "what", "value_mm", "minimum_mm", "key")
def _fab_minimum(f):
    return "net class %s: %s %.3g mm is below the fab's minimum %.3g mm (fab-profile.json min.%s)" % (
        f["net_class"], f["what"], f["value_mm"], f["minimum_mm"], f["key"])


# ------------------------------------------------------------------ what refused a scan
def _loc(at) -> str:
    return "(%.2f, %.2f)" % (at[0], at[1])


def blame_text(entries: list) -> str:
    """The rejection counts of a scan (blame.blame_of) and, for each kind, the owners that caused most of them."""
    from .refusals import Owner, Refusal
    parts = []
    for e in entries:
        n = e["count"]
        if e["form"] == "vias":
            parts.append("vias that could not give way x%d" % n)
        elif e["form"] == "rider":
            parts.append("%s x%d" % (Refusal.from_json(e["reason"]), n))
        else:
            detail = "" if not e["owners"] else ": " + ", ".join(
                "%s%s x%d" % (Owner.from_json(o["owner"]), (" %s face" % o["faces"]) if o["faces"] else "", o["count"])
                for o in e["owners"])
            parts.append("%s x%d%s" % (e["label"], n, detail))
    return "; ".join(parts)


def counts_text(counts: list) -> str:
    """"courtyard x12, edge x3": a scan's refusals by kind, most first."""
    return ", ".join("%s x%d" % (k, n) for k, n in counts)


def room_lost_text(room_lost: dict) -> str:
    """What a part with no legal spot says of the look-ahead of a limit partner placed before it: that no room was left
    for it, or that room was left and what was placed since took it."""
    out = ""
    if room_lost.get("gone"):
        out += "; see: no room was left for it when %s was placed" % ", ".join(room_lost["gone"])
    if room_lost.get("kept"):
        out += "; the look-ahead left it room when %s was placed, but what was placed since took it" % ", ".join(room_lost["kept"])
    return out


def where_text(w: dict) -> str:
    """Where a one-freedom item slides: {"form": "edge", "edge": "north"}, "run" (facing_deg), "rim" (word), "ring"
    (radius_mm), "spoke" (angle_deg), "line" (axis, at_mm, and `toward` or `across` as it was seeded)."""
    form = w["form"]
    if form == "edge":
        return "along the %s edge" % w["edge"]
    if form == "run":
        return "along the run facing %.0f degrees" % w["facing_deg"]
    if form == "rim":
        return "round the %s" % w["word"]
    if form == "ring":
        return "round the %.2f mm ring" % w["radius_mm"]
    if form == "spoke":
        return "out along the %.0f degree spoke" % w["angle_deg"]
    seeded = ("; as far %s as it is legal" % w["toward"]) if w.get("toward") else \
        "; across from what it connects to" if w.get("across") else ""
    return "on the line %s = %.2f%s" % (w["axis"], w["at_mm"], seeded)


def _refusal(d) -> str:
    from .refusals import Refusal
    return str(Refusal.from_json(d))


def _riders(riders: list) -> str:
    return "".join("; %s" % _refusal(r) for r in riders)


def pocket_note(f: dict) -> str:
    """What a pocket search says, without the item's key."""
    if f["variant"] == "any_rotation":
        return "no pocket fits its %.1f x %.1f envelope on the %s face at any rotation asked for" % (
            f["w_mm"], f["h_mm"], f["face"])
    return "no pocket fits its %.1f x %.1f envelope on the %s face (%d pocket(s) tried)%s" % (
        f["w_mm"], f["h_mm"], f["face"], f["tried"], _riders(f.get("riders", ())))


def turns_text(turns: list) -> str:
    """"0: ...; 90: ...": a refusal at each rotation tried."""
    return "; ".join("%g: %s" % (rot, _refusal(why)) for rot, why in turns)


def block_alone_note(f: dict) -> str:
    return "cannot be laid out on its own at any rotation it may take, whatever room the board has (%s)" % turns_text(f["turns"])


def riders_alone_note(f: dict) -> str:
    return "cannot be laid out with its riders at any rotation it may take, whatever room the board has (%s)" % turns_text(f["turns"])


def rides_note(f: dict) -> str:
    return "rides %s, which found no place" % f["rider_of"]


@renders(C.UNPLACED_SEARCH, "item", "radius_mm", "at", "blame")
def _unplaced_search(f):
    blame = "no legal location within %.1f mm of %s (%s)" % (f["radius_mm"], _loc(f["at"]), blame_text(f["blame"]))
    if f.get("pocket_tried") is not None:
        blame += "; no pocket took it (%d tried)" % f["pocket_tried"]
    return "%s: %s%s" % (f["item"], blame, room_lost_text(f.get("room_lost", {})))


@renders(C.UNPLACED_POCKET, "item", "variant", "w_mm", "h_mm", "face")
def _unplaced_pocket(f):
    return "%s: %s" % (f["item"], pocket_note(f))


@renders(C.UNPLACED_SLIDE, "item", "where", "counts")
def _unplaced_slide(f):
    return "%s: no room anywhere %s (%s)%s" % (f["item"], where_text(f["where"]), counts_text(f["counts"]),
                                             _riders(f.get("riders", ())))


@renders(C.UNPLACED_BLOCK, "item", "variant")
def _unplaced_block(f):
    if f["variant"] == "alone":
        return "%s: %s" % (f["item"], block_alone_note(f))
    return "%s: no legal spot within %.1f mm of %s (%s)" % (f["item"], f["radius_mm"], _loc(f["at"]), counts_text(f["counts"]))


@renders(C.UNPLACED_BEARING, "item", "turns", "counts")
def _unplaced_bearing(f):
    return "%s: no bearing of %d tried leaves it legal on its point (%s)" % (f["item"], f["turns"], counts_text(f["counts"]))


@renders(C.UNPLACED_RIDES, "item", "variant")
def _unplaced_rides(f):
    return "%s: %s" % (f["item"], riders_alone_note(f) if f["variant"] == "alone" else rides_note(f))


@renders(C.FIXED_PART, "item", "freedom", "why")
def _fixed_part(f):
    return "%s (%s): %s" % (f["item"], f["freedom"], _refusal(f["why"]))
