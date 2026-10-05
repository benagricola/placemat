"""Why a candidate placement was refused, as data.

Occupancy, the edge shapes and the give-way search used to return a sentence for a refusal and let the placer count them,
join them and parse them. A `Refusal` is the same answer as a record: a `code` (what kind of conflict) and `facts`, JSON
values the judging site measured (who, where, how far, what was needed). `str(refusal)` is the sentence this module renders
from them, so a step's note, a console line or a finding shows the same words it always did; nothing else reads the
sentence, and the placer counts a refusal by its `bucket`.

A refusal that only answers "whether" (`say=False`) has a code and no facts, and renders nothing.

Names: a refdes as a refusal names it is a `W`, `[name, cell]` (`cell` empty for a part outside a cell), written
"cell NAME's REF" for a cell's member and as itself otherwise.
Figures are in millimetres and their names say so. Copper is `{"net": ..., "who": W}`, written as its net, else as who.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum

from .cutouts import EdgeWhy
from .geometry import gap_texts


class Code(str, Enum):
    """What a refusal is about. A str-valued enum: the value is the string form a record carries."""
    VIA_BAN = "via_ban"
    LEAD_UNDER = "lead_under"
    CLAIMED_COURTYARD = "claimed_courtyard"
    DRAWN_OVERLAP = "drawn_overlap"
    DRAWN_NEAR = "drawn_near"
    HOLE_TO_HOLE = "hole_to_hole"
    HOLE_COPPER = "hole_copper"
    COURTYARD_OVERLAP = "courtyard_overlap"
    COURTYARD_OVER = "courtyard_over"
    COPPER_NEAR = "copper_near"
    NPTH_CUTS = "npth_cuts"
    NPTH_NEAR = "npth_near"
    EDGE = "edge"
    RESERVATION = "reservation"
    # the give-way search: why a carried via cannot give way, and what refuses an item because of one
    CANNOT_GIVE_WAY = "cannot_give_way"
    SHARED_BY = "shared_by"
    VIA_RING_EDGE = "via_ring_edge"
    TRACK_EDGE = "track_edge"
    NO_VIA_TO_SHARE = "no_via_to_share"
    NO_CLEAR_TAIL = "no_clear_tail"
    NO_SPOT = "no_spot"
    NO_SPOT_LEAVE = "no_spot_leave"
    NO_SPOT_ROUTED = "no_spot_routed"
    SHORTER_VIA_REFUSED = "shorter_via_refused"
    PLACES_WITH = "places_with"
    OPTION_VIA = "option_via"
    NOT_A_PLANE_NET = "not_a_plane_net"
    SERVES_NO_PAD = "serves_no_pad"
    KEEPS_DROPS = "keeps_drops"
    # what an item's search is asked besides the board: its riders, the sensitive parts' limits, the look-ahead
    RIDER = "rider"
    EXPOSURE = "exposure"
    LOOKAHEAD_FAR = "lookahead_far"
    LOOKAHEAD_DIST = "lookahead_dist"
    LOOKAHEAD_SPOT = "lookahead_spot"
    # where a via or a via's tail may not stand
    OFF_BOARD = "off_board"
    SITE_COPPER = "site_copper"
    SITE_HOLE_VIA = "site_hole_via"
    SITE_COPPER_VIA = "site_copper_via"
    SITE_COPPER_HOLE = "site_copper_hole"
    SITE_COPPER_TRACK = "site_copper_track"
    SITE_COPPER_POUR = "site_copper_pour"
    SITE_COPPER_OWN_HOLE = "site_copper_own_hole"
    SITE_PAD_HOLE = "site_pad_hole"
    SITE_UNPLATED = "site_unplated"
    SITE_KEEPOUT = "site_keepout"
    TAIL_VIA = "tail_via"
    TAIL_CROSSES = "tail_crosses"
    TAIL_COPPER = "tail_copper"
    SOURCE_PAD = "source_pad"
    # what stands in the way of an escape's lane or its via (lanes.py)
    LANE_LANE = "lane_lane"
    LANE_VIA = "lane_via"
    LANE_HOLE = "lane_hole"
    LANE_PASSED_VIA = "lane_passed_via"
    LANE_PASSED_JOG = "lane_passed_jog"
    LANE_PAD_JOG = "lane_pad_jog"
    LANE_PAD = "lane_pad"
    LANE_NO_SPOT = "lane_no_spot"
    # why an adopted route cannot be drawn where the parts now stand
    ROUTE_GONE = "route_gone"
    ROUTE_FACE = "route_face"
    ROUTE_NO_PAD = "route_no_pad"
    ROUTE_NET = "route_net"
    ROUTE_MOVED = "route_moved"
    ROUTE_END = "route_end"
    # why a hole or a region may not go where it is put
    CUTOUT_OUTSIDE = "cutout_outside"
    CUTOUT_NOTCH = "cutout_notch"
    CUTOUT_WEB = "cutout_web"
    CUTOUT_MILLED = "cutout_milled"
    CUTOUT_SILK = "cutout_silk"
    KEEPOUT_OFF_BOARD = "keepout_off_board"
    CUTOUT_NOWHERE = "cutout_nowhere"
    # why a track's arc does not fit, and why a Past has nothing to stand off
    ARC_TURNS_BACK = "arc_turns_back"
    ARC_LEG = "arc_leg"
    PAST_AFTER = "past_after"
    PAST_NOT_PLANNED = "past_not_planned"
    PAST_NO_VIA = "past_no_via"
    PAST_NO_TRACK = "past_no_track"
    PAST_CUTOUT_UNPLACED = "past_cutout_unplaced"
    PAST_OFF_BOARD = "past_off_board"
    # where a via may stand, asked of the board as it was read (queries.py)
    Q_OFF_BOARD = "q_off_board"
    Q_EDGE = "q_edge"
    Q_COPPER = "q_copper"
    Q_OWN_COPPER = "q_own_copper"
    Q_HOLE = "q_hole"
    Q_NPTH = "q_npth"
    Q_KEEPOUT = "q_keepout"
    Q_POUR = "q_pour"
    Q_TAIL = "q_tail"
    # a block laid out from its anchor
    BLOCK_ANCHOR = "block_anchor"
    BLOCK_NO_SPOT = "block_no_spot"
    BLOCK_TAKEN = "block_taken"


# the native keep-in's codes (native/src/board.rs): 7 is the box test of a rectangular board
EDGE_OF_NATIVE = {1: EdgeWhy.OUTSIDE, 2: EdgeWhy.IN_CUTOUT, 3: EdgeWhy.PAST_BOARD, 4: EdgeWhy.PAST_CUTOUT,
                  5: EdgeWhy.PAST_RIM, 6: EdgeWhy.INTO_BORE, 7: EdgeWhy.CROSSES}

FLAT_EDGE_MARGIN = 2e-5
"""How far inside the edge a courtyard or body is held, mm (native/src/board.rs `FLAT_EDGE_MARGIN`): twice the nanometre a
placement is rounded to, which is the least a box test sees a box crossing a cutout or an outline's side by."""

_NAMES = {"silk": "silk", "mask": "mask opening", "body": "body", "pad": "pad", "through": "pad", "npth": "hole"}

_KEEP_IN = {EdgeWhy.PAST_BOARD: ("past the board", "board's"), EdgeWhy.PAST_CUTOUT: ("past the cutout", "cutout's"),
            EdgeWhy.PAST_RIM: ("past the rim", "rim's"), EdgeWhy.INTO_BORE: ("into the bore", "bore's")}


def is_flat(margin_mm: float) -> bool:
    """Whether a margin is the one a courtyard or body is held at: the edge itself."""
    return margin_mm <= FLAT_EDGE_MARGIN


@dataclass(frozen=True)
class ReservedBy:
    """What put a reservation there, in parts: a keepout (`name`, its `why`, and the `max_height_mm` that admits short parts),
    a push (`name` the source's label, `limit`, `radius_mm`, its `why`), a part's fanout (`name` its item, `side`), a label
    (`name` the label's key without its word), or anything else (`name` the whole phrase)."""
    kind: str = "other"
    name: str = ""
    why: str = ""
    max_height_mm: float | None = None
    limit: float | None = None
    radius_mm: float | None = None
    side: str = ""
    item: str = ""                      # a label: the item it is on (`name` is the item and the text)

    def __str__(self) -> str:
        if self.kind == "keepout":
            tall = ("; parts up to %g mm tall may sit here, and a part with no Pm.Height counts as taller"
                    % self.max_height_mm) if self.max_height_mm is not None else ""
            return "keepout %r (%s%s)" % (self.name, self.why, tall)
        if self.kind == "push":
            return "push from %s (limit %.3g at %.3g mm)%s" % (self.name, self.limit, self.radius_mm,
                                                               (": %s" % self.why) if self.why else "")
        if self.kind == "fanout":
            return "fanout of %s (%s side)" % (self.name, self.side)
        if self.kind == "label":
            return "label %s" % self.name
        return self.name

    def to_json(self) -> dict:
        return {k: v for k, v in (("kind", self.kind), ("name", self.name), ("why", self.why),
                                  ("max_height_mm", self.max_height_mm), ("limit", self.limit),
                                  ("radius_mm", self.radius_mm), ("side", self.side),
                                  ("item", self.item)) if v not in ("", None)}

    @staticmethod
    def from_json(d: dict) -> "ReservedBy":
        return ReservedBy(**d)


def reserved_by(why) -> ReservedBy:
    """A reservation's `why` as a ReservedBy: one is kept, a phrase becomes an `other`."""
    return why if isinstance(why, ReservedBy) else ReservedBy("other", str(why))


@dataclass(frozen=True)
class Owner:
    """Who a refusal blamed, as a scan tallies it: a part (`name`, in `cell`), copper of a net, an escape lane, or a
    reservation (and the member of an item in it, or its own copper). Hashable, so a scan counts by it; `str` is how a
    finding names it."""
    form: str                           # who | lane | reserved | member_in | own_copper
    name: str = ""
    cell: str = ""
    net: str = ""
    by: ReservedBy | None = None

    def __str__(self) -> str:
        if self.form == "lane":
            return self.name
        if self.form == "reserved":
            return str(self.by)
        if self.form == "member_in":
            return "%s in %s" % (self.name, self.by)
        if self.form == "own_copper":
            return "its own copper in %s" % self.by
        base = who_text([self.name, self.cell])
        return "%s %s" % (base, self.net) if self.net else base

    def to_json(self) -> dict:
        out = {"form": self.form}
        for k in ("name", "cell", "net"):
            if getattr(self, k):
                out[k] = getattr(self, k)
        if self.by is not None:
            out["by"] = self.by.to_json()
        return out

    @staticmethod
    def from_json(d: dict) -> "Owner":
        by = d.get("by")
        return Owner(d["form"], d.get("name", ""), d.get("cell", ""), d.get("net", ""),
                     None if by is None else ReservedBy.from_json(by))


def who_text(w) -> str:
    """A W as a refusal names it."""
    name, cell = w
    return "cell %s's %s" % (cell, name) if cell else name


def _copper(c: dict) -> str:
    return c["net"] or who_text(c["who"])


def _hole(h: dict, possessive: bool = False) -> str:
    form = h["form"]
    if form == "part":
        return "%s's hole" % who_text(h["who"])
    name = "cell %s's via" % h["name"] if form == "cell_via" else "the via %s" % h["name"] if form == "via_at" else "a via"
    return name + "'s hole" if possessive else name


def _box(b) -> str:
    return "%.2f,%.2f..%.2f,%.2f" % tuple(b)


def _got_want(f: dict) -> tuple:
    return gap_texts(f["gap_mm"], f["need_mm"])


def edge_phrase(verdict, margin_mm: float) -> str:
    """What the edge says, as "is ..." follows it: "outside the board", "past the board edge", "past the cutout's keep-in
    (0.25 mm)". The margin is a keep-in unless it is the edge itself."""
    verdict = EdgeWhy(verdict)
    if verdict is EdgeWhy.CROSSES:
        return "crosses the board edge" + ("" if is_flat(margin_mm) else " margin (%.2f mm)" % margin_mm)
    if verdict is EdgeWhy.OUTSIDE:
        return "outside the board"
    if verdict is EdgeWhy.IN_CUTOUT:
        return "inside a cutout"
    head, owner = _KEEP_IN[verdict]
    if is_flat(margin_mm):
        return head + " edge"
    return "%s's keep-in (%.2f mm)" % (head, margin_mm)


@dataclass(frozen=True)
class EdgeFault:
    """What the edge says of a box and the margin it was asked with: the phrase a label or a refusal finishes "is ..." with."""
    verdict: EdgeWhy
    margin_mm: float

    def __str__(self) -> str:
        return edge_phrase(self.verdict, self.margin_mm)

    def to_json(self) -> dict:
        return {"verdict": self.verdict.value, "margin_mm": self.margin_mm}


# ------------------------------------------------------------------ the record
class Refusal:
    """A refusal: `code` and `facts`. `str()` is its sentence, rendered when asked for; `bucket` is what a scan counts it
    under. Two refusals are equal when their code and facts are."""
    __slots__ = ("code", "facts")

    def __init__(self, code: Code, **facts):
        self.code = code
        self.facts = facts

    def __str__(self) -> str:
        return render(self)

    def __repr__(self) -> str:
        return "Refusal(%s, %r)" % (self.code.value, self.facts)

    def __eq__(self, other) -> bool:
        return isinstance(other, Refusal) and self.code is other.code and self.facts == other.facts

    def __hash__(self) -> int:
        return hash((self.code, json.dumps(self.facts, sort_keys=True, default=str)))

    @property
    def tally(self) -> str:
        """What a search for a via's spot counts this refusal under: the kind of thing in the way."""
        fn = TALLY.get(self.code)
        return fn(self.facts) if fn is not None else self.bucket

    @property
    def bucket(self) -> str:
        return BUCKET[self.code](self.facts) if self.facts or self.code not in _FACTLESS else _FACTLESS[self.code]

    def to_json(self) -> dict:
        return {"code": self.code.value, **{k: _json(v) for k, v in self.facts.items()}}

    @staticmethod
    def from_json(d: dict) -> "Refusal":
        d = dict(d)
        return Refusal(Code(d.pop("code")), **{k: _unjson(k, v) for k, v in d.items()})


def _json(v):
    if isinstance(v, Refusal):
        return v.to_json()
    if isinstance(v, (ReservedBy, Owner)):
        return v.to_json()
    if isinstance(v, (list, tuple)):
        return [_json(x) for x in v]
    if isinstance(v, Enum):
        return v.value
    return v


_SUBREFUSALS = frozenset(("base", "why_not", "edge", "note", "why", "nearest"))


def _unjson(key: str, v):
    if key == "by" and isinstance(v, dict):
        return ReservedBy.from_json(v)
    if key in _SUBREFUSALS:
        if isinstance(v, dict):
            return Refusal.from_json(v)
        if isinstance(v, list):
            return [Refusal.from_json(x) for x in v]
    return v


def render(r: Refusal) -> str:
    fn = RENDER.get(r.code)
    if fn is None or (not r.facts and r.code in _FACTLESS):
        raise ValueError("a refusal that carries no facts (%s) has no sentence" % r.code.value)
    return fn(r.facts)


RENDER: dict = {}
BUCKET: dict = {}
TALLY: dict = {}
_FACTLESS = {Code.COPPER_NEAR: "copper", Code.HOLE_COPPER: "copper", Code.HOLE_TO_HOLE: "hole-to-hole"}
"""A `say=False` answer: the kind alone, and the bucket it counts under."""


def renders(code: Code, bucket):
    """Register the sentence of `code` and its bucket: a string, or a function of the facts."""
    def register(fn):
        RENDER[code] = fn
        BUCKET[code] = bucket if callable(bucket) else (lambda f, b=bucket: b)
        return fn
    return register


def first_word(w) -> str:
    return who_text(w).split(" ")[0]


# ------------------------------------------------------------------ occupancy
@renders(Code.VIA_BAN, lambda f: f["ban"].split(" ")[0])
def _via_ban(f):
    return "%s forbids vias: the %s via at (%.2f, %.2f) is inside it" % (
        f["ban"], f["net"] or "unnetted", f["at"][0], f["at"][1])


@renders(Code.LEAD_UNDER, "courtyard")
def _lead_under(f):
    return "%s courtyard sits over the through-hole lead of %s%s%s" % (
        who_text(f["court"]), who_text(f["lead"]), " pad %s" % f["pad"] if f["pad"] else "",
        "" if not f["netless"] else " (a plated pad with no net: often a footprint defect)")


@renders(Code.CLAIMED_COURTYARD, "courtyard")
def _claimed_courtyard(f):
    return "%s %s sits in %s courtyard, which it claims as it draws nothing else" % (
        who_text(f["other"]), _NAMES.get(f["other_kind"], f["other_kind"]), who_text(f["claim"]))


@renders(Code.DRAWN_OVERLAP, lambda f: first_word(f["a"]))
def _drawn_overlap(f):
    return "%s %s overlaps %s %s" % (who_text(f["a"]), _NAMES[f["a_kind"]], who_text(f["b"]), _NAMES[f["b_kind"]])


@renders(Code.DRAWN_NEAR, lambda f: first_word(f["a"]))
def _drawn_near(f):
    got, want = _got_want(f)
    return "%s %s is %s mm from %s %s (needs %s)" % (
        who_text(f["a"]), _NAMES[f["a_kind"]], got, who_text(f["b"]), _NAMES[f["b_kind"]], want)


@renders(Code.HOLE_TO_HOLE, "hole-to-hole")
def _hole_to_hole(f):
    got, want = _got_want(f)
    return "%s %s mm from %s (hole-to-hole needs %s)" % (_hole(f["a"]), got, _hole(f["b"]), want)


@renders(Code.HOLE_COPPER, "copper")
def _hole_copper(f):
    got, want = _got_want(f)
    return "%s copper %s mm from %s (needs %s)" % (_copper(f["metal"]), got, _hole(f["hole"], True), want)


@renders(Code.COURTYARD_OVERLAP, "courtyard")
def _courtyard_overlap(f):
    return "%s courtyard overlaps %s courtyard" % (who_text(f["a"]), who_text(f["b"]))


@renders(Code.COURTYARD_OVER, "courtyard")
def _courtyard_over(f):
    return "%s courtyard sits over a %s (%s)" % (
        who_text(f["court"]), f["hole_kind"], who_text(f["owner"]) if f["owner"] else "via")


def _layers(f) -> str:
    return "/".join(f["layers"])


@renders(Code.COPPER_NEAR, "copper")
def _copper_near(f):
    got, want = _got_want(f)
    need = want + (", rule: %s" % f["rule"] if f.get("rule") else "")
    form = f["form"]
    if form == "via":
        x, y = f["at"]
        return "via %s at (%.2f, %.2f)%s is %s mm from %s copper on %s (needs %s)" % (
            f["net"] or "-", x, y, " (%s)" % f["via_at"] if f.get("via_at") else "", got, _copper(f["other"]),
            _layers(f), need)
    if form == "track":
        (ax, ay), (bx, by) = f["ends"]
        who = "%s %s (%.2f, %.2f)-(%.2f, %.2f)" % ("arc track" if f["arc"] else "track", f["net"] or "-", ax, ay, bx, by)
    else:
        who = "%s %s %s" % (who_text(f["who"]), f["what"], f["net"] or "-")
    return "%s is %s mm from %s copper on %s (needs %s)" % (who, got, _copper(f["other"]), _layers(f), need)


@renders(Code.NPTH_CUTS, "copper")
def _npth_cuts(f):
    return "%s hole cuts %s copper" % (who_text(f["hole"]), _copper(f["metal"]))


@renders(Code.NPTH_NEAR, "copper")
def _npth_near(f):
    got, want = _got_want(f)
    return "%s copper %s mm from %s's unplated hole (needs %s)" % (_copper(f["metal"]), got, who_text(f["hole"]), want)


def _edge_bucket(f) -> str:
    """"edge" where the sentence says the edge (a copper or label silk box, a box test, a flat margin), else "body": the
    first word of "body box ... is outside the board", which a scan has always counted these under."""
    if f["what"] in ("copper", "silk") or EdgeWhy(f["verdict"]) is EdgeWhy.CROSSES:
        return "edge"
    if EdgeWhy(f["verdict"]) in _KEEP_IN and is_flat(f["margin_mm"]):
        return "edge"
    return "body"


@renders(Code.EDGE, _edge_bucket)
def _edge(f):
    label = {"copper": "copper to edge: box", "silk": "label silk to edge: box"}.get(f["what"], "body box")
    verdict = EdgeWhy(f["verdict"])
    if verdict is EdgeWhy.CROSSES:
        return "%s %s %s" % (label, _box(f["box"]), edge_phrase(verdict, f["margin_mm"]))
    return "%s %s is %s" % (label, _box(f["box"]), edge_phrase(verdict, f["margin_mm"]))


def _parts_said(parts) -> list:
    out = []
    for ref, state, h in parts:
        out.append("%s is barred" % ref if state == "barred" else
                   "%s has no Pm.Height" % ref if state == "no_height" else "%s is %g mm" % (ref, h))
    return out


@renders(Code.RESERVATION, "reservation")
def _reservation(f):
    by = f["by"]
    if f["variant"] == "own_copper":
        return "its own copper sits in the reservation for %s" % by
    if f["variant"] == "member":
        why = "its member %s sits in the reservation for %s" % (f["member"], by)
        said = _parts_said(f["parts"])
        return why + (": " + said[0] if said else "")
    why = "sits in the reservation for %s" % by
    said = _parts_said(f["parts"])
    return why + (": " + ", ".join(said) if said else "")


# ------------------------------------------------------------------ the give-way search
def _of(of) -> str:
    form, name = of
    return "cell %s" % name if form == "cell" else name


def _via_where(f) -> str:
    return "the via %s at (%.2f, %.2f) (%s)" % (f["net"], f["at"][0], f["at"][1], _of(f["of"]))


@renders(Code.CANNOT_GIVE_WAY, "via cannot give way")
def _cannot_give_way(f):
    """`base`, the refusal that met the via; `via`, the via that cannot (None for one of the item's own); `why_not`, the
    reasons it cannot: each a refusal, said in a row."""
    said = ", ".join(str(x) for x in f["why_not"])
    if f.get("via") is None:
        return "%s; it cannot give way: %s" % (f["base"], said)
    return "%s; %s cannot give way: %s" % (f["base"], _via_where(f["via"]), said)


@renders(Code.SHARED_BY, "via cannot give way")
def _shared_by(f):
    return "the via at (%.2f, %.2f) of %s shares it" % (f["at"][0], f["at"][1], _of(f["by"]))


@renders(Code.VIA_RING_EDGE, lambda f: "edge")
def _via_ring_edge(f):
    return "via %s at (%.2f, %.2f): its ring %s" % (f["net"] or "-", f["at"][0], f["at"][1], f["edge"])


@renders(Code.TRACK_EDGE, lambda f: "edge")
def _track_edge(f):
    (ax, ay), (bx, by) = f["ends"]
    return "%s track from (%.2f, %.2f) to (%.2f, %.2f): its track %s" % (f["net"] or "-", ax, ay, bx, by, f["edge"])


@renders(Code.NO_VIA_TO_SHARE, "via cannot give way")
def _no_via_to_share(f):
    return "no %s via within %.2f mm to share" % (f["net"], f["reach_mm"])


@renders(Code.NO_CLEAR_TAIL, "via cannot give way")
def _no_clear_tail(f):
    return "no tail to the %s via%s within %.2f mm is clear" % (f["net"], "s" if f["n"] > 1 else "", f["reach_mm"])


@renders(Code.NO_SPOT, "via cannot give way")
def _no_spot(f):
    return "no spot within %.2f mm%s is clear" % (f["reach_mm"], " inside its pad" if f["inside"] else "")


@renders(Code.NO_SPOT_LEAVE, "via cannot give way")
def _no_spot_leave(f):
    return "no spot within %.2f mm is clear to leave its pad by a tail" % f["reach_mm"]


@renders(Code.NO_SPOT_ROUTED, "via cannot give way")
def _no_spot_routed(f):
    return "no spot within %.2f mm%s is clear with its %d tracks rebuilt" % (
        f["reach_mm"], " inside its pad" if f["inside"] else "", f["tracks"])


@renders(Code.SHORTER_VIA_REFUSED, "via cannot give way")
def _shorter_via_refused(f):
    return "a %s via from %s to %s would clear this; the fab profile does not allow %s vias" % (
        f["via"], f["from_layer"], f["to_layer"], f["via"])


@renders(Code.PLACES_WITH, "via cannot give way")
def _places_with(f):
    return "no spot; it places with %s" % f["note"]


@renders(Code.OPTION_VIA, "via cannot give way")
def _option_via(f):
    return "a %s via shortened to %s-%s (via.%s is if-needed in fab-profile.json)" % (
        f["via"], f["from_layer"][:-3], f["to_layer"][:-3], f["via"])


@renders(Code.NOT_A_PLANE_NET, "via cannot give way")
def _not_a_plane_net(f):
    return "%s is not a plane net, so it is no drop" % f["net"]


@renders(Code.SERVES_NO_PAD, "via cannot give way")
def _serves_no_pad(f):
    return "it serves no pad of its own"


@renders(Code.KEEPS_DROPS, "via cannot give way")
def _keeps_drops(f):
    return "%s pad %s keeps %d of its %d drops, and must keep %d" % (f["pad"][0], f["pad"][1], f["keeps"], f["of"], f["must"])


# ------------------------------------------------------------------ what a search asks besides the board
@renders(Code.RIDER, lambda f: "rider %s" % f["key"])
def _rider(f):
    return "rider %s: %s" % (f["key"], f["why"])


@renders(Code.EXPOSURE, lambda f: "%s's %s limit" % (f["sens"], f["kind"]))
def _exposure(f):
    return "%s's %s limit: the sources add to %.3g%s here, over the %.3g left" % (
        f["sens"], f["kind"], f["total"], f["unit"], f["bound"])


def _room_bucket(f) -> str:
    return "no room left for %s" % f["partners"]


@renders(Code.LOOKAHEAD_FAR, _room_bucket)
def _lookahead_far(f):
    return "%s: no legal spot of %s is far enough from here for its %s limit" % (_room_bucket(f), f["other"], f["kind"])


@renders(Code.LOOKAHEAD_DIST, _room_bucket)
def _lookahead_dist(f):
    return "%s: no legal spot of %s is %.3g mm from here" % (_room_bucket(f), f["other"], f["reach_mm"])


@renders(Code.LOOKAHEAD_SPOT, "lookahead")
def _lookahead_spot(f):
    raise ValueError("a look-ahead's recording refusal has no sentence")


def _aim(a: dict) -> str:
    """Which anchor pad a satellite was aimed at: `ref`, `pad`, `net`, and `carrying`, the number of the anchor's pads on
    that net when the script named none of them (0 otherwise)."""
    text = "%s pad %s (%s" % (a["ref"], a["pad"], a["net"])
    if a["carrying"] > 1:
        text += ", the first of its %d pads on it: name a pad number to aim at another" % a["carrying"]
    return text + ")"


_KNOWN = ("courtyard", "edge", "reservation", "copper", "through", "npth", "hole-to-hole")


def _anchor_bucket(f) -> str:
    """The bucket of a refusal of a block's anchor: its own where that is a kind of conflict, else "anchor:", the first
    word the sentence has always started with."""
    why = f["why"]
    return why.bucket if why.bucket in _KNOWN or why.bucket == "via cannot give way" else "anchor:"


@renders(Code.BLOCK_ANCHOR, _anchor_bucket)
def _block_anchor(f):
    return "anchor: " + str(f["why"])


@renders(Code.BLOCK_NO_SPOT, lambda f: "%s:" % f["sat"])
def _block_no_spot(f):
    return "%s: no legal spot on the axis of %s, nor slid up to %g mm along its row" % (f["sat"], _aim(f["aim"]), f["reach_mm"])


@renders(Code.BLOCK_TAKEN, lambda f: "%s:" % f["sat"])
def _block_taken(f):
    return "%s: no legal spot on the axis of %s; %s already sits there: aim at another pad, or link it instead" % (
        f["sat"], _aim(f["aim"]), ", ".join(f["there"]))


# ------------------------------------------------------------------ where a via or its tail may stand
def copper_name(c: dict) -> str:
    """Copper a finding names, as `Occupancy.name_copper` gives it: {"form": "pad", "who": W, "label", "net"} (a part's pad),
    {"form": "via", "net"}, {"form": "track", "net"} or {"form": "copper", "net"}."""
    form, net = c["form"], c.get("net", "")
    if form == "pad":
        return "%s pad %s (%s)" % (who_text(c["who"]), c["label"], net or "no net")
    if form == "via":
        return "a %s via" % (net or "unnetted")
    if form == "track":
        return "a %s track" % (net or "unnetted")
    return "%s copper" % (net or "unnetted")


@renders(Code.OFF_BOARD, "edge")
def _off_board(f):
    if f["variant"] == "rect":
        return "within %.2f mm of the board edge" % f["keep_in_mm"]
    return "off the board, or within %.2f mm of the board edge" % f["keep_in_mm"]


@renders(Code.SITE_COPPER, "copper")
def _site_copper(f):
    return "copper %s" % f["why"]


@renders(Code.SITE_HOLE_VIA, "hole-to-hole")
def _site_hole_via(f):
    got, want = _got_want(f)
    return "hole %s mm from the %s via's hole (needs %s)" % (got, f["net"], want)


@renders(Code.SITE_COPPER_VIA, "copper")
def _site_copper_via(f):
    got, want = _got_want(f)
    return "copper %s mm from the %s via (needs %s)" % (got, f["net"], want)


@renders(Code.SITE_COPPER_HOLE, "copper")
def _site_copper_hole(f):
    got, want = _got_want(f)
    return "copper %s mm from %s hole (needs %s)" % (got, "the %s via's" % f["net"] if f["of"] == "via" else "its", want)


@renders(Code.SITE_COPPER_TRACK, "copper")
def _site_copper_track(f):
    got, want = _got_want(f)
    return "copper %s mm from a %s track planned before it (needs %s)" % (got, f["net"], want)


@renders(Code.SITE_COPPER_POUR, "copper")
def _site_copper_pour(f):
    got, want = _got_want(f)
    return "copper %s mm from a %s pour planned before it (needs %s)" % (got, f["net"], want)


@renders(Code.SITE_COPPER_OWN_HOLE, "copper")
def _site_copper_own_hole(f):
    got, want = _got_want(f)
    return "copper %s mm from its hole (needs %s)" % (got, want)


@renders(Code.SITE_PAD_HOLE, "copper")
def _site_pad_hole(f):
    got, want = _got_want(f)
    return ("hole %s mm from a pad's hole (needs %s)" if f["what"] == "hole" else
            "copper %s mm from a pad's hole (needs %s)") % (got, want)


@renders(Code.SITE_UNPLATED, "copper")
def _site_unplated(f):
    got, want = _got_want(f)
    return ("hole %s mm from an unplated hole (needs %s)" if f["what"] == "hole" else
            "copper %s mm from an unplated hole (needs %s)") % (got, want)


@renders(Code.SITE_KEEPOUT, "keepout")
def _site_keepout(f):
    return "inside a keepout, which forbids vias"


@renders(Code.TAIL_VIA, "copper")
def _tail_via(f):
    got, want = _got_want(f)
    return "tail %s mm from the %s via (needs %s)" % (got, f["net"], want)


@renders(Code.TAIL_CROSSES, "copper")
def _tail_crosses(f):
    return "tail crosses a %s track planned before it" % f["net"]


@renders(Code.TAIL_COPPER, "copper")
def _tail_copper(f):
    return "tail %s" % f["why"]


def tallied(code: Code, bucket):
    """Register what a via search counts `code` under, where that is not its scan bucket."""
    def register(fn):
        TALLY[code] = bucket if callable(bucket) else (lambda f, b=bucket: b)
        return fn
    return register


for _code, _kind in ((Code.OFF_BOARD, "edge"), (Code.SITE_COPPER, "copper"), (Code.SITE_HOLE_VIA, "hole"),
                     (Code.SITE_COPPER_VIA, "copper"), (Code.SITE_COPPER_HOLE, "copper"),
                     (Code.SITE_COPPER_TRACK, "copper"), (Code.SITE_COPPER_POUR, "copper"),
                     (Code.SITE_COPPER_OWN_HOLE, "copper"), (Code.SITE_KEEPOUT, "keepout"), (Code.TAIL_VIA, "tail"),
                     (Code.TAIL_CROSSES, "tail"), (Code.TAIL_COPPER, "tail"), (Code.SOURCE_PAD, "pad"),
                     (Code.Q_OFF_BOARD, "edge"), (Code.Q_EDGE, "edge"), (Code.Q_OWN_COPPER, "copper"),
                     (Code.Q_HOLE, "hole"), (Code.Q_NPTH, "copper"), (Code.Q_KEEPOUT, "keepout"),
                     (Code.Q_TAIL, "tail")):
    tallied(_code, _kind)(None)
tallied(Code.SITE_PAD_HOLE, lambda f: f["what"])(None)
tallied(Code.SITE_UNPLATED, lambda f: f["what"])(None)
tallied(Code.Q_COPPER, lambda f: f["kind"])(None)


@renders(Code.SOURCE_PAD, "pad")
def _source_pad(f):
    return "in the source pad"


# ------------------------------------------------------------------ where a via may stand, from the board as read
def _hole_of_board(h: dict) -> str:
    """A hole the board has: {"form": "pad", "ref", "number"}, {"form": "npth", "ref"} or {"form": "via", "net"}."""
    if h["form"] == "pad":
        return "%s pad %s" % (h["ref"], h["number"])
    if h["form"] == "npth":
        return "%s hole" % h["ref"]
    return "via %s" % h["net"]


@renders(Code.Q_OFF_BOARD, "edge")
def _q_off_board(f):
    return "off the board"


@renders(Code.Q_EDGE, "edge")
def _q_edge(f):
    got, want = _got_want(f)
    return "%s mm from the board edge (needs %s)" % (got, want)


@renders(Code.Q_COPPER, lambda f: f["kind"])
def _q_copper(f):
    got, want = _got_want(f)
    return "%s mm from %s %s on %s (needs %s)" % (got, f["net"] or "-", f["kind"], "/".join(f["layers"]), want)


@renders(Code.Q_OWN_COPPER, "copper")
def _q_own_copper(f):
    got, want = _got_want(f)
    return "%s mm from %s's own copper on %s (needs %s)" % (got, f["ref"], f["layer"], want)


@renders(Code.Q_HOLE, "hole")
def _q_hole(f):
    got, want = _got_want(f)
    return "hole %s mm from the %s hole (needs %s)" % (got, _hole_of_board(f["hole"]), want)


@renders(Code.Q_NPTH, "copper")
def _q_npth(f):
    got, want = _got_want(f)
    return "copper %s mm from %s's unplated hole (needs %s)" % (got, f["ref"], want)


@renders(Code.Q_KEEPOUT, "keepout")
def _q_keepout(f):
    return "inside %s, which forbids vias" % f["base"]


@renders(Code.Q_POUR, "pour")
def _q_pour(f):
    return "the %s pour on %s would give way" % (f["net"], "/".join(f["layers"]))


@renders(Code.Q_TAIL, "tail")
def _q_tail(f):
    got, want = _got_want(f)
    return "tail %s mm from %s %s on %s (needs %s)" % (got, f["net"] or "-", f["kind"], f["layer"], want)


# ------------------------------------------------------------------ copper that cannot be drawn as asked
@renders(Code.ARC_TURNS_BACK, "copper")
def _arc_turns_back(f):
    return "the track turns back on itself at (%.2f, %.2f)" % (f["at"][0], f["at"][1])


@renders(Code.ARC_LEG, "copper")
def _arc_leg(f):
    """`leg`: the two ends; `length_mm`; `arcs`: each {"radius_mm", "at", "turn_deg" (as written), "takes_mm"}."""
    (ax, ay), (bx, by) = f["leg"]
    first = f["arcs"][0]
    text = ("the leg (%.2f, %.2f)-(%.2f, %.2f) is %.2f mm, and the arc of radius %.2f mm at its corner (%.2f, %.2f), a turn "
            "of %s degrees, takes %.2f mm of it" % (ax, ay, bx, by, f["length_mm"], first["radius_mm"], first["at"][0],
                                                    first["at"][1], first["turn_deg"], first["takes_mm"]))
    return text + "".join(" and the one at (%.2f, %.2f), a turn of %s degrees, %.2f mm" % (
        a["at"][0], a["at"][1], a["turn_deg"], a["takes_mm"]) for a in f["arcs"][1:])


@renders(Code.PAST_AFTER, "copper")
def _past_after(f):
    return "%s is declared after %s; declare it first" % (f["key"], f["what"])


@renders(Code.PAST_NOT_PLANNED, "copper")
def _past_not_planned(f):
    return "%s is not planned by then" % f["key"]


@renders(Code.PAST_NO_VIA, "copper")
def _past_no_via(f):
    return "that via found no spot"


@renders(Code.PAST_NO_TRACK, "copper")
def _past_no_track(f):
    return "that track is not drawn"


@renders(Code.PAST_CUTOUT_UNPLACED, "copper")
def _past_cutout_unplaced(f):
    return "cutout %s found no place" % f["name"]


@renders(Code.PAST_OFF_BOARD, "copper")
def _past_off_board(f):
    return "its point (%.2f, %.2f) lies %s" % (f["at"][0], f["at"][1],
                                               "in a cutout" if f["edge"] == "in_cutout" else "off the board")


# ------------------------------------------------------------------ a hole or a region put where it may not go
@renders(Code.CUTOUT_OUTSIDE, "edge")
def _cutout_outside(f):
    return "reaches outside the board"


@renders(Code.CUTOUT_NOTCH, "edge")
def _cutout_notch(f):
    return "touches the board outline: that is a notch, not a hole, and it belongs in the board's own outline path"


@renders(Code.CUTOUT_WEB, "edge")
def _cutout_web(f):
    return "would leave a %.2f mm web, under the %.2f mm minimum" % (f["gap_mm"], f["web_mm"])


@renders(Code.CUTOUT_MILLED, "edge")
def _cutout_milled(f):
    return "would be milled through %s" % f["owner"]


@renders(Code.CUTOUT_SILK, "edge")
def _cutout_silk(f):
    got, want = _got_want(f)
    return "would stand %s mm from %s's silk (the silk clearance is %s)" % (got, f["owner"], want)


@renders(Code.KEEPOUT_OFF_BOARD, "edge")
def _keepout_off_board(f):
    return "is wholly off the board"


@renders(Code.CUTOUT_NOWHERE, "edge")
def _cutout_nowhere(f):
    """`nearest`: the refusal nearest the place the region wanted to be, or None where there was no place at all."""
    return "has nowhere legal to go: %s" % (f["nearest"] or "nowhere on the board")


# ------------------------------------------------------------------ an adopted route that cannot be drawn
def _inst(i: dict) -> str:
    """A part as an adopted route names it: `name` (the instance a script names) and `ref` (the refdes KiCad shows)."""
    return i["name"] if i["ref"] == i["name"] else "%s (%s)" % (i["name"], i["ref"])


@renders(Code.ROUTE_GONE, "route")
def _route_gone(f):
    return "%s is no longer on the board" % _inst(f["part"])


@renders(Code.ROUTE_FACE, "route")
def _route_face(f):
    return "%s is on the other face now" % _inst(f["part"])


@renders(Code.ROUTE_NO_PAD, "route")
def _route_no_pad(f):
    return "%s has no pad %s now" % (_inst(f["part"]), f["number"])


@renders(Code.ROUTE_NET, "route")
def _route_net(f):
    return "%s pad %s is on %s now" % (_inst(f["part"]), f["number"], f["net"] or "no net")


@renders(Code.ROUTE_MOVED, "route")
def _route_moved(f):
    return "%s has moved or turned relative to %s since it was adopted" % (
        _inst(f["part"]), ", ".join(_inst(o) for o in f["others"]) if f["others"] else "its own pads")


@renders(Code.ROUTE_END, "route")
def _route_end(f):
    return "its end at (%.2f, %.2f) no longer meets the net's other copper" % (f["at"][0], f["at"][1])


# ------------------------------------------------------------------ what stands in the way of an escape's lane or via
def _got_want3(f: dict) -> tuple:
    return gap_texts(f["gap_mm"], f["need_mm"], 3)


@renders(Code.LANE_LANE, "lane")
def _lane_lane(f):
    got, want = _got_want3(f)
    return "the lane of pin %s, %s mm off (needs %s)" % (f["pin"], got, want)


@renders(Code.LANE_VIA, "lane")
def _lane_via(f):
    got, want = _got_want3(f)
    return "the via of pin %s, %s mm off (needs %s)" % (f["pin"], got, want)


@renders(Code.LANE_HOLE, "lane")
def _lane_hole(f):
    got, want = _got_want3(f)
    return "the hole of pin %s's via, %s mm off (hole to hole needs %s)" % (f["pin"], got, want)


@renders(Code.LANE_PASSED_VIA, "lane")
def _lane_passed_via(f):
    got, want = _got_want3(f)
    return "the via of pin %s, passed by the lane %s mm off (needs %s)" % (f["pin"], got, want)


@renders(Code.LANE_PASSED_JOG, "lane")
def _lane_passed_jog(f):
    got, want = _got_want3(f)
    return "the lane of pin %s, passed by the jog %s mm off (needs %s)" % (f["pin"], got, want)


@renders(Code.LANE_PAD_JOG, "lane")
def _lane_pad_jog(f):
    got, want = _got_want3(f)
    return "pad %s of its own part, passed by the jog %s mm off (needs %s)" % (f["pin"], got, want)


@renders(Code.LANE_PAD, "lane")
def _lane_pad(f):
    got, want = _got_want3(f)
    return "pad %s of its own part, %s mm off (needs %s)" % (f["pin"], got, want)


@renders(Code.LANE_NO_SPOT, "lane")
def _lane_no_spot(f):
    return "its via has no legal spot within %.1f mm: %s" % (f["reach_mm"], f["why"] or "nothing stands in its way")
