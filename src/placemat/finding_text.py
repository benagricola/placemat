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


def _by_list(by: list) -> str:
    """Who blocks a pad: each an Owner as JSON, as a finding names them ("copper" for none)."""
    from .refusals import Owner
    return ", ".join(str(Owner.from_json(o)) for o in by) or "copper"


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


@renders(C.LABEL_CELL_EDGE, "cell", "text", "edge", "cutout", "gap_mm", "need_mm")
def _label_cell_edge(f):
    """A label of a cell whose place the script decided, nearer the board edge than the silk clearance. `edge`: "outline"
    or "cutout"; `cutout`: the cutout's name, None for the outline or an unnamed hole."""
    where = "the board outline" if f["edge"] == "outline" else \
        ("cutout %s" % f["cutout"] if f["cutout"] is not None else "a cutout")
    return "cell %s label %s: %.2f mm from %s, under the %.2f mm silk clearance" % (
        f["cell"], f["text"], f["gap_mm"], where, f["need_mm"])


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
        f["ref"], f["pin"], f["net"], _list(f["joins"], "what it joins"), _by_list(f["by"]))


@renders(C.ESCAPE_WALLED, "variant", "ref", "pin", "net", "by")
def _escape_walled(f):
    if f["variant"] == "handoff":
        return ("%s pin %s (%s): no other pad is on the net, so it leaves the board here, and it is walled off by %s"
                % (f["ref"], f["pin"], f["net"], _by_list(f["by"])))
    return "%s pin %s (%s): walled off by %s" % (f["ref"], f["pin"], f["net"], _by_list(f["by"]))


@renders(C.ESCAPE_LANE, "ref", "pin", "net", "blocked")
def _escape_lane(f):
    return "%s pin %s (%s): its lane is blocked by %s" % (f["ref"], f["pin"], f["net"], "; ".join(_refusal(b) for b in f["blocked"]))


@renders(C.ESCAPE_VIA_UNNEEDED, "ref", "pin", "net", "layers", "via")
def _escape_via_unneeded(f):
    via, (x, y) = f["via"], f["via"]["at"]
    if via["kind"] == "lane":
        what, fix = "the via at (%.2f, %.2f) that ends its lane" % (x, y), "take the pin out of the escape's vias="
    else:
        what, fix = "via %s at (%.2f, %.2f), on its lane's copper," % (f["net"], x, y), "remove the board.via"
    return ("%s pin %s (%s): %s is not needed: the lane reaches the frame's edge on %s without it, so it can end there for "
            "the parent board's router; %s" % (f["ref"], f["pin"], f["net"], what, "/".join(f["layers"]), fix))


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


_PIN_PROBLEMS = {
    "no_pin": "%(key)s names pin %(name)s, which %(ref)s does not have; the study runs without it",
    "no_net": "%(key)s names net %(name)s, which no pin of %(ref)s carries; the study runs without %(entry)s",
    "no_names": "%(key)s names %(name)s by pin name, and no pin names were read for %(ref)s: its symbol is not among "
                "the board's libraries; the study runs without it",
    "unreadable": "%(key)s entry %(entry)s is not name:pins; the study runs without it",
    "not_in_pool": "%(key)s entry %(entry)s names pin %(name)s, which is not an unfixed pin of its Pm.PinPool; the study "
                   "runs without the group",
    "two_groups": "%(key)s entry %(entry)s names pin %(name)s, which an earlier group has; the study runs without it",
    "bad_marker": "%(key)s entry %(entry)s marks its group with %(name)s, and a single ! (hard) is the only marker; the "
                  "study runs without the group",
    "same_name": "%(key)s entries %(entry)s name two groups %(name)s; the study runs without the second",
    "no_legal_pin": "net %(name)s has no pin of the pool left that %(key)s lets it take; %(ref)s is not studied",
    "no_legal_map": "no map gives every net a pin it may take: %(name)s has none left; %(ref)s is not studied",
    "present_breaks": "net %(name)s stands on pin %(pin)s, against its %(rule)s; the capture breaks its own rule",
}


@renders(C.SETUP_PINS, "ref", "key", "entry", "code", "name")
def _setup_pins(f):
    if f["code"] == "study_failed":
        return "the pin map study failed with %s: %s; this resolve has no pin map findings" % (f["type"], f["message"])
    if f["code"] == "study_slow":
        return ("%s: the pin map study ran past its wall-clock guard, pins.guard_ms of %g ms, after %d of its %d steps; it "
                "gives no map, since one cut short by the time is not the study's answer" % (
                    " and ".join(f["refs"]), f["guard_ms"], f["steps"], f["budget_steps"]))
    if f["code"] == "no_legal_pin" and f.get("held_net"):
        return "%s: net %s may take only pin %s, which net %s holds; %s is not studied" % (
            f["ref"], f["name"], f["held_pin"], f["held_net"], f["ref"])
    return "%s: %s" % (f["ref"], _PIN_PROBLEMS[f["code"]] % f)


def _weighted(n: float, how: str) -> str:
    """'8 fewer weighted crossings', '1 more weighted crossing'."""
    n = round(n, 1)
    return "%g %s weighted crossing%s" % (n, how, "" if n == 1 else "s")


TOGETHER_MM = 0.05          # a soft group spread less than this is together, in the text


def _saving(present: dict, r: dict, before=()) -> str:
    """What a pose's best map saves against the present one: its plainest saving of weighted crossings, airwire or
    turning, and each soft group it brings together or nearer (`before`: the groups as they stand), and what it gives
    up on weighted crossings or airwire to win. A term that grows is never said as a negative saving: a map that saves
    nothing (one that keeps the pin rules the present map breaks) is said by what it costs."""
    dw = present["weighted"] - r["weighted"]
    dl = present["length_mm"] - r["length_mm"]
    db = present["bend_deg"] - r["bend_deg"]
    won = []
    if dw > 1e-9:
        won.append(_weighted(dw, "fewer"))
    elif dl > 1e-9:
        won.append("%.1f mm less airwire" % dl)
    elif db >= 0.5:
        won.append("%.0f degrees less turning at its pins" % db)
    was = {(g["ref"], g["name"]): g["spread_mm"] for g in before}
    for g in r.get("groups", ()):
        old = was.get((g["ref"], g["name"]))
        if g["hard"] or old is None or g["spread_mm"] >= old - 1e-9:
            continue
        won.append("group %s %s" % (g["name"], "brought together" if g["spread_mm"] < TOGETHER_MM else "nearer together"))
    lost = []
    if dw < -1e-9:
        lost.append(_weighted(-dw, "more"))
    if dl < -1e-9:
        lost.append("%.1f mm more airwire" % -dl)
    dt = present["total"] - r["total"]
    if not won and (dt >= 0 or not lost):
        won.append("%.1f %s in the total" % (abs(dt), "less" if dt >= 0 else "more"))
    return " and ".join(won + lost)


def split_groups(row: dict) -> list:
    """The soft groups a pose's map leaves split: spread at least TOGETHER_MM."""
    return [g for g in row.get("groups", ()) if not g["hard"] and g["spread_mm"] >= TOGETHER_MM]


def pose_text(turns: list) -> str:
    """'90 degrees', '90 degrees on the back', or for parts studied together 'U1 at 90 degrees and U2 at 180 degrees'."""
    def one(t):
        return "%g degrees%s" % (t["rotation_deg"], " on the %s" % t["face"] if t["flip"] else "")
    if len(turns) == 1:
        return one(turns[0])
    return " and ".join("%s at %s" % (t["ref"], one(t)) for t in turns)


def at_pose(turns: list) -> str:
    """'at 90 degrees' for a part turned alone, 'with cell logic turned to 90 degrees' for one studied as its cell."""
    if not any("cell" in t for t in turns):
        return "at " + pose_text(turns)
    return "with " + " and ".join("cell %s turned to %g degrees" % (t["cell"], t["cell_rotation_deg"]) if "cell" in t
                                  else "%s at %s" % (t["ref"], pose_text([t])) for t in turns)


def _module(t: dict) -> str:
    return "module %s" % t["module"] if t.get("module") else "the module of cell %s" % t["cell"]


def _frame(t: dict) -> str:
    """The frame a part's rotation in its module is given in: the module's own, or the arrangement the cell stands in."""
    a = t.get("arrangement", "default")
    return "its frame" if a in ("", "default") else "the frame of its arrangement %s" % a


def cell_levers(t: dict) -> str:
    """The two ways to take a turn of a part studied as its cell (a turn record with `cell`). The second re-lays the
    module, so every stamp of it."""
    every = ", which re-lays all %d of its stamps" % t["stamps"] if t.get("stamps", 1) > 1 else ""
    return ("turn cell %s to %g degrees on the board, or keep it and re-lay %s with %s at %g degrees in %s and the "
            "cell's other parts placed round it%s; either one means the next run re-places the board" % (
                t["cell"], t["cell_rotation_deg"], _module(t), t["ref"], t["module_rotation_deg"], _frame(t), every))


def levers_text(turns: list) -> str:
    """The levers of each cell a pose turns, each named when it turns more than one."""
    cells = [t for t in turns if "cell" in t and (t["turn_deg"] or t["flip"])]
    if len(cells) == 1:
        return cell_levers(cells[0])
    return "; ".join("for cell %s, %s" % (t["cell"], cell_levers(t)) for t in cells)


def cell_capture(t: dict) -> str:
    """Whose capture a map of a part in a cell changes: 'module M's capture, which its 2 stamps share'."""
    whose = "module %s's capture" % t["module"] if t.get("module") else "the capture of cell %s's module" % t["cell"]
    return whose + (", which its %d stamps share" % t["stamps"] if t.get("stamps", 1) > 1 else "")


def _stamp_moves(s: dict) -> str:
    moves = "keeps its pins" if not s["moves"] else \
        "moves pins %s" % ", ".join("%s->%s" % (m["from"], m["to"]) for m in s["moves"])
    return "%s %s with %s at %g degrees in the module's frame" % (s["cell"], moves, s["ref"], s["module_rotation_deg"])


def _plural(n: int, one: str, many: str) -> str:
    return "%d %s" % (n, one if n == 1 else many)


@renders(C.PINS_REMAP, "ref", "refs", "present", "rotations", "best", "first_map", "budget_out", "budget_steps", "steps",
         "searched",
         "of", "routed", "present_breaks")
def _pins_remap(f):
    turns = f["rotations"][f["best"]]["turns"] if f["rotations"] else []
    cell_of = {t["ref"]: t["cell"] for t in turns if "cell" in t}
    if f.get("cell") and not cell_of:
        cell_of = {f["refs"][0]: f["cell"]}
    who = " and ".join("%s in cell %s" % (r, cell_of[r]) if r in cell_of else r for r in f["refs"])
    if f.get("withheld"):
        w = f["withheld"]
        missing = w["of"] - w["placed"]
        return ("%s: the pin map study waits on placement: %d of its %d movable nets %s no placed far end, and "
                "pins.placed_share_min asks for %g percent with one; no map or turn is advised" % (
                    who, missing, w["of"], "has" if missing == 1 else "have", round(w["share_min"] * 100, 1)))
    their = "their present rotations" if len(f["refs"]) > 1 else \
        "the cell's present rotation" if f.get("cell") else "its present rotation"
    if not f["first_map"]:
        return "%s: the pin map study had no steps for a first map: its budget is %d steps; pins.budget_steps sets it" % (
            who, f["budget_steps"])
    rs, p = f["rotations"], f["present"]
    here, best = rs[0], rs[f["best"]]
    if here["total"] < p["total"] - 1e-9:
        text = "%s: a pin map with %s exists at %s" % (who, _saving(p, here, f.get("present_groups", ())), their)
    elif f["present_breaks"]:
        text = "%s: a pin map that keeps the pin rules the present one breaks exists at %s, at %s" % (
            who, their, _saving(p, here, f.get("present_groups", ())))
    else:
        text = "%s: no better pin map at %s" % (who, their)
    if f["best"] != 0:
        text += "; %s, %s" % (at_pose(best["turns"]), _saving(p, best, f.get("present_groups", ())))
        if any("cell" in t and (t["turn_deg"] or t["flip"]) for t in best["turns"]):
            text += "; to take that turn, " + levers_text(best["turns"])
    split = split_groups(best)
    if split:
        text += "; " + "; ".join("group %s ends split, %.1f mm beyond its pin pitch" % (g["name"], g["spread_mm"])
                                 for g in split)
    lead = next((t for t in best["turns"] if "cell" in t and t["cell"] == f.get("cell")), None)
    if lead is not None and any(m["ref"] == lead["ref"] for m in best["map"]):
        text += "; the map is a change to " + cell_capture(lead)
    if f["routed"]:
        text += "; %d of the nets it moves %s copper now: %s" % (len(f["routed"]), "has" if len(f["routed"]) == 1 else "have",
                                                              ", ".join(f["routed"]))
    waiting = sorted({h["net"] for h in f.get("held", ()) if h["why"] == "unplaced"})
    if waiting:
        text += "; %s until %s placed: %s" % (
            _plural(len(waiting), "net keeps its pin", "nets keep their pins"),
            "its far end is" if len(waiting) == 1 else "their far ends are", ", ".join(waiting))
    if f.get("stamp_maps"):
        sm = f["stamp_maps"]
        maps = any(s["moves"] != sm[0]["moves"] for s in sm)
        turns = any(s["module_rotation_deg"] != sm[0]["module_rotation_deg"] for s in sm)
        what = "different best maps and module rotations" if maps and turns else \
            "different best maps" if maps else "different module rotations"
        text += "; the %d stamps of %s have %s: %s" % (len(sm), _module({"module": f.get("module"), "cell": f["cell"]}),
                                                      what, "; ".join(_stamp_moves(s) for s in sm))
    if f["budget_out"]:
        text += "; the study stopped at its budget of %d steps after %d of %d poses" % (f["budget_steps"], f["searched"],
                                                                                         f["of"])
    return text


@renders(C.SETUP_PAIR_LAYERS, "key", "variant", "layers", "missing", "board_layers")
def _setup_pair_layers(f):
    if f["variant"] == "no_pair":
        return ("route.pair_layers %s: no differential pair on this board has those two nets or that net class; the entry is "
                "not used" % f["key"])
    return "route.pair_layers %s: names %s, which this board does not have (it has %s); the pair routes on the route's own layers" % (
        f["key"], ", ".join(f["missing"]), ", ".join(f["board_layers"]))


@renders(C.SETUP_NET_HALO, "variant", "net", "halo_mm")
def _setup_net_halo(f):
    if f["variant"] == "no_net":
        return "route.net_halos %s: no net of that name on this board; the entry is not used" % f["net"]
    if f["variant"] == "open":
        return ("%s is open (%d item(s)) and routed with the other nets: the router spaces every net of that pass %.2f mm "
                "from all copper, not only from %s; draw %s whole in the module, or route it alone as a `[route] islands` "
                "net" % (f["net"], f["open_items"], f["halo_mm"], f["net"], f["net"]))
    return ("%s pad %s.%s is inside %s's %.2f mm halo; its copper ends %.2f mm away where a track leaving it needs %.2f mm, "
            "%.2f mm short: draw its escape out past the halo in the module (a longer run= on its board.escape), or give %s "
            "a smaller halo" % (f["pad_net"], f["ref"], f["number"], f["net"], f["halo_mm"], f["reach_mm"], f["needed_mm"],
                                f["short_mm"], f["net"]))


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
    """The rejection counts of a scan (blame.blame_of) and, for each kind, the owners that caused most of them; a "pocket" entry
    (an arrangement note's default that fits no pocket) says so, and a "counts" entry (a slide's or a point's) gives the counts."""
    from .refusals import Owner, Refusal
    parts = []
    for e in entries:
        if e["form"] == "pocket":                   # a search that never ran: no pocket fits the item (Board._no_pocket_note)
            parts.append(pocket_note(e))
            continue
        if e["form"] == "counts":                   # a slide's or a point's refusals by kind (blame.counts_of): no owners to name
            parts.append(counts_text(e["counts"]))
            continue
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
    head, tail = where_parts(w)
    return head + (("; " + tail) if tail else "")


def where_parts(w: dict) -> tuple:
    """(where, how it was seeded): `where_text` without its "; "-joined tail; the tail is "" for all but a line."""
    form = w["form"]
    if form == "edge":
        return "along the %s edge" % w["edge"], ""
    if form == "run":
        return "along the run facing %.0f degrees" % w["facing_deg"], ""
    if form == "rim":
        return "round the %s" % w["word"], ""
    if form == "ring":
        return "round the %.2f mm ring" % w["radius_mm"], ""
    if form == "spoke":
        return "out along the %.0f degree spoke" % w["angle_deg"], ""
    seeded = ("as far %s as it is legal" % w["toward"]) if w.get("toward") else \
        "across from what it connects to" if w.get("across") else ""
    return "on the line %s = %.2f" % (w["axis"], w["at_mm"]), seeded


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
    scan = ""
    if f.get("scanned"):
        scan = "; a scan of the whole face found no legal spot" + ("" if not f.get("budget") else " (%s)" % budget_text(f["budget"]))
    return "no pocket fits its %.1f x %.1f envelope on the %s face (%d pocket(s) tried)%s%s" % (
        f["w_mm"], f["h_mm"], f["face"], f["tried"], scan, _riders(f.get("riders", ())))


def turns_text(turns: list) -> str:
    """"0: ...; 90: ...": a refusal at each rotation tried. A turn tagged with an arrangement ([rotation, refusal, id]) says it
    first: "c_in.east at 0: ..."."""
    return "; ".join(("%s at " % t[2] if len(t) > 2 else "") + "%g: %s" % (t[0], _refusal(t[1])) for t in turns)


def block_alone_note(f: dict) -> str:
    return "cannot be laid out on its own at any rotation it may take, whatever room the board has (%s)" % turns_text(f["turns"])


def riders_alone_note(f: dict) -> str:
    return "cannot be laid out with its riders at any rotation it may take, whatever room the board has (%s)" % turns_text(f["turns"])


def rides_note(f: dict) -> str:
    return "rides %s, which found no place" % f["rider_of"]


def budget_text(b: dict) -> str:
    """What a search that spent its step budget says of how far it got: `placer.SearchBudget.measurement()`."""
    return "the search stopped at its budget of %d candidates, with %.1f%% of the search area covered" % (
        b["limit"], b["share"] * 100.0)


@renders(C.UNPLACED_SEARCH, "item", "radius_mm", "at", "blame")
def _unplaced_search(f):
    if f.get("budget"):
        blame = "no legal location found within %.1f mm of %s (%s); %s" % (
            f["radius_mm"], _loc(f["at"]), blame_text(f["blame"]), budget_text(f["budget"]))
    else:
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
    among = " in any of %d arrangements" % f["arrangements"] if f.get("arrangements") else ""
    return "%s: no bearing of %d tried%s leaves it legal on its point (%s)" % (f["item"], f["turns"], among, counts_text(f["counts"]))


@renders(C.UNPLACED_RIDES, "item", "variant")
def _unplaced_rides(f):
    return "%s: %s" % (f["item"], riders_alone_note(f) if f["variant"] == "alone" else rides_note(f))


@renders(C.FIXED_PART, "item", "freedom", "why")
def _fixed_part(f):
    """A decided item that is not legal where it was put; a cell with several arrangements, none legal, names each other
    arrangement's refusal after the one it stands in."""
    others = "".join("; arrangement %s: %s" % (a["id"], _refusal(a["why"])) for a in f.get("arrangements", ()))
    return "%s (%s): %s%s" % (f["item"], f["freedom"], _refusal(f["why"]), others)


# ------------------------------------------------------------------ copper that is not drawn as asked
def _span(span) -> str:
    return "%s-%s" % (span[0], span[1])


def _copper_name(c: dict) -> str:
    from .refusals import copper_name
    return copper_name(c)


def _unplanned(f: dict) -> str:
    return _refusal(f["why"])


def _not_drawn_arc(f):
    return ("track %s: not drawn, an arc of radius %.2f mm does not fit: %s; a smaller radius=, points further apart%s"
            % (f["net"], f["radius_mm"], _refusal(f["misfit"]),
               ", or Bend.ARC_FREE where the octilinear legs made the short leg" if f["free_hint"] else ""))


_NOT_DRAWN = {
    "via_lost": lambda f: "track %s: its end on %s is not drawn, because that via found no spot" % (
        f["track"], ", ".join(f["lost"])),
    "past": lambda f: "%s: its point past %s is not drawn, because %s" % (f["item"], ", ".join(f["names"]), _refusal(f["why"])),
    "arc": _not_drawn_arc,
    "through": lambda f: "track %s: not drawn, it would run through %s%s" % (
        f["net"], _copper_name(f["met"]), " and %d more" % (len(f["blockers"]) - 1) if len(f.get("blockers", ())) > 1 else ""),
    "pair_close": lambda f: "pair %s/%s: its pad pairs are too close for a centreline of its own; give the centreline's "
                            "points" % (f["p"], f["n"]),
    "vias_span": lambda f: "vias %s: a span of %s does not reach %s.%s on %s" % (
        f["net"], _span(f["span"]), f["owner"], f["number"], f["layer"]),
    "vias_row": lambda f: "vias %s: %d of %d along %s.%s's axis, the next stands %s" % (
        f["net"], f["placed"], f["of"], f["owner"], f["number"], _refusal(f["why"])),
    "field_span": lambda f: "vias %s: a span of %s does not reach %s.%s on %s" % (
        f["net"], _span(f["span"]), f["owner"], f["number"], "/".join(f["layers"])),
    "field_none": lambda f: "vias %s: no via fits in %s.%s, or clears the copper and holes round it (%.2f mm via, %.2f mm "
                            "drill, %.2f mm inset)" % (f["net"], f["owner"], f["number"], f["size_mm"], f["drill_mm"], f["inset_mm"]),
    "via_stand": lambda f: "via %s at (%.2f, %.2f): not drawn, it would stand on %s" % (
        f["net"], f["at"][0], f["at"][1], _copper_name(f["met"])),
    "tail_join": lambda f: "via %s: its tail on %s would not join %s.%s, which is not on that layer" % (
        f["net"], f["layer"], f["owner"], f["number"]),
    "tail_span": lambda f: "via %s: a span of %s does not reach its tail on %s" % (f["net"], _span(f["span"]), f["layer"]),
    "via_nowhere": lambda f: "via %s: nowhere within %.2f mm of %s.%s, %d spot(s) tried: %s" % (
        f["net"], f["radius_mm"], f["owner"], f["number"], f["tried"], counts_text(f["counts"])),
    "pour_unplanned": lambda f: "pour %s: %s" % (f["net"], _unplanned(f)),
    "pour_via_net": lambda f: "pour %s: %s is on net %s, and a fitted pour holds only its own net's copper" % (
        f["net"], _member(f["member"]), f["on_net"]),
    "pour_pad_net": lambda f: "pour %s: pad %s is on net %s, and a fitted pour holds only its own net's pads" % (
        f["net"], _member(f["member"]), f["on_net"] or "-"),
    "pour_via_span": lambda f: "pour %s: %s does not span %s (it spans %s)" % (
        f["net"], _member(f["member"]), f["layer"], _span(f["span"])),
    "pour_pad_layer": lambda f: "pour %s: pad %s has no copper on %s" % (f["net"], _member(f["member"]), f["layer"]),
    "pour_close": lambda f: "pour %s: %s is within its clearance of %s %s, so no pour can hold the %s clear; the pour is not "
                            "drawn" % (f["net"], _blocker(f), f["noun"], _between(f), f["noun"]),
    "pour_enclosed": lambda f: "pour %s: %s stands between %ss %s with no way round it; the pour is not drawn" % (
        f["net"], _blocker(f), f["noun"], _between(f)),
    "pour_no_way": lambda f: "pour %s: %s leaves no way between %ss %s; the pour is not drawn" % (
        f["net"], _blocker(f), f["noun"], _between(f)),
    "pour_no_area": lambda f: "pour %s: its pads leave no area to fit; the pour is not drawn" % f["net"],
    "pour_no_reach": lambda f: "pour %s: reach= leaves no copper joined to its pads; the pour is not drawn" % f["net"],
    "pour_carriers": lambda f: "pour %s: reach=Reach.CURRENT sizes the pour for the current between two of its parts, and %s "
                               "of its pads' parts carries current on %s (Pm.I); the pour is not drawn" % (
                                   f["net"], "none" if not f["carriers"] else "only %s" % f["carriers"][0], f["net"]),
    "plane_outside": lambda f: "plane %s: its items lie outside the frame, so it is not drawn" % f["net"],
}


def _member(m) -> str:
    """A fitted pour's member: a pad `[owner, number]` as "OWNER.NUMBER", a via `[x, y]` as "via at (x, y)"."""
    if m[0] == "pad":
        return "%s.%s" % (m[1], m[2])
    return "via at (%.2f, %.2f)" % (m[1], m[2])


def _between(f) -> str:
    return " and ".join(_member(m) for m in f["between"])


def _blocker(f) -> str:
    """What stands in a fitted pour's way: copper as a finding names it, or "other copper"."""
    what = f.get("what")
    if what is None:
        return "other copper"
    form = what["form"]
    if form == "unplated":
        return "%s's unplated hole" % _who(what["who"])
    if form == "via":
        return "via %s at (%.2f, %.2f)" % (what["net"] or "-", what["at"][0], what["at"][1])
    if form == "track":
        (ax, ay), (bx, by) = what["ends"]
        return "%s %s (%.2f, %.2f)-(%.2f, %.2f)" % ("arc track" if what["arc"] else "track", what["net"] or "-", ax, ay, bx, by)
    if form == "pad":
        return "%s pad %s (%s)" % (_who(what["who"]), what["label"], what["net"] or "no net")
    if form == "owned":
        return "%s copper %s" % (_who(what["who"]), what["net"] or "-")
    if form == "edge":
        return "the board edge"
    return ("pour %s" % what["net"]) if what.get("net") else "copper"


def _who(w) -> str:
    from .refusals import who_text
    return who_text(w)


@renders(C.COPPER_NOT_DRAWN, "variant")
def _copper_not_drawn(f):
    return _NOT_DRAWN[f["variant"]](f)


_NOTE = {
    "waypoint": lambda f: "track %s: a waypoint steers it into another net's pad; drawn pad to pad it clears, so drop the "
                          "waypoint(s) unless the route must go there" % f["net"],
    "between_gap": lambda f: "track %s: the gap between %s.%s and %s.%s is %.3f mm, not enough for a %.2f mm track with "
                             "clearance to each (%.3f mm needed)" % (
                                 f["net"], f["a"][0], f["a"][1], f["b"][0], f["b"][1], f["gap_mm"], f["width_mm"], f["need_mm"]),
    "pour_narrow": lambda f: "pour %s: narrows to %.2f mm at (%.2f, %.2f), under its net's %.2f mm track" % (
        f["net"], f["width_mm"], f["at"][0], f["at"][1], f["need_mm"]),
    "pour_neck": lambda f: ("pour %s: the room runs out at %.2f mm of reach (up to %.2f mm tried): it narrows to %.2f mm at "
                            "(%.2f, %.2f), where %g A between %s and %s needs %.2f mm at a %g C rise%s; drawn at that width" % (
                                f["net"], f["reach_mm"], f["reach_max_mm"], f["width_mm"], f["at"][0], f["at"][1], f["amps"],
                                f["start"], f["to"], f["need_mm"], f["rise_c"],
                                "; %s stands there" % _blocker(f) if f.get("what") is not None else "")),
}


@renders(C.COPPER_NOTE, "variant")
def _copper_note(f):
    return _NOTE[f["variant"]](f)


@renders(C.COPPER_CORNER, "net", "edge", "names", "near_mm", "need_mm")
def _copper_corner(f):
    return ("track %s: the points either side of its 45 past the %s corner of %s allow no 45 through it; the track passes "
            "that corner at %.3f mm, under the %.3f mm clearance" % (f["net"], f["edge"], ", ".join(f["names"]),
                                                                       f["near_mm"], f["need_mm"]))


_STITCH = {
    "no_region": lambda f: "stitch %s: its region is not drawn, so there is nothing to stitch over" % f["net"],
    "none": lambda f: "stitch %s: no via fits in the region at a %.2f mm pitch" % (f["net"], f["pitch_mm"]),
    "gap": lambda f: "stitch %s: the %s side's row has a %.2f mm gap, over its %.2f mm pitch" % (
        f["net"], f["side"], f["gap_mm"], f["pitch_mm"]),
    "no_edge": lambda f: "stitch %s: no edge of the region faces the sides asked for" % f["net"],
    "none_outside": lambda f: "stitch %s: no via fits outside the region at a %.2f mm pitch" % (f["net"], f["pitch_mm"]),
    "left_out": lambda f: "stitch %s: %d via(s) outside the region left out: %s" % (
        f["net"], len(f["left_out"]), "; ".join("(%.2f, %.2f) %s" % (x, y, _refusal(why)) for x, y, why in f["left_out"])),
    "rows": lambda f: "stitch %s: rows by the region's side as turned -> the board's side: %s" % (
        f["net"], ", ".join("%s side -> board %s" % (a, b) for a, b in f["rows"])),
}


@renders(C.COPPER_STITCH, "variant")
def _copper_stitch(f):
    return _STITCH[f["variant"]](f)


@renders(C.COPPER_MEETS, "net", "hit")
def _copper_meets(f):
    text = "copper %s: %s" % (f["net"], _refusal(f["hit"]))
    if f.get("chamfer_at"):
        text += "; the 45 of its chamfer at (%.2f, %.2f); a smaller chamfer= there keeps clear" % tuple(f["chamfer_at"])
    elif f.get("arc_at"):
        text += "; the arc of its corner (radius %.2f mm) at (%.2f, %.2f); a smaller radius= there keeps clear" % (
            f["arc_radius_mm"], f["arc_at"][0], f["arc_at"][1])
    return text


@renders(C.SETUP_PCBNEW, "net", "variant")
def _setup_pcbnew(f):
    return "pour %s: reach%s needs KiCad's pcbnew at plan time, for its polygon booleans; the pour is not drawn" % (
        f["net"], "=Reach.CURRENT" if f["variant"] == "current" else "=")


def native_text(f: dict) -> str:
    """The native accelerator's status record (geometry.NativeStatus.facts) as a sentence, with what to do."""
    reason, ours, theirs = f["reason"], f["placemat_version"], f.get("native_version")
    rebuild = "rebuild it from this checkout's native/ (uv pip install -e \".[native]\")"
    if reason == "version_mismatch":
        have = "placemat_native %s" % theirs if theirs else "a placemat_native with no version"
        return "%s does not match placemat %s, so the pure Python path runs: results are the same, 5-10x slower on a large board; %s" % (
            have, ours, rebuild)
    if reason == "not_installed":
        return "placemat_native is not installed, so the pure Python path runs: results are the same, 5-10x slower on a large board; install it (uv pip install -e \".[native]\")"
    if reason == "import_error":
        return "placemat_native would not import (%s), so the pure Python path runs: results are the same, 5-10x slower on a large board; %s" % (
            f.get("detail") or "no detail", rebuild)
    if reason == "disabled_by_env":
        return "PLACEMAT_NATIVE=0 is set, so the pure Python path runs: results are the same, 5-10x slower on a large board; unset it to use native"
    return "placemat_native is in use"


@renders(C.SETUP_NATIVE, "reason", "placemat_version", "native_version", "detail")
def _setup_native(f):
    return native_text(f)


@renders(C.FIXED_CUTOUT, "name", "why")
def _fixed_cutout(f):
    return "%s (cutout): %s" % (f["name"], _refusal(f["why"]))


@renders(C.FIXED_KEEPOUT, "name", "why")
def _fixed_keepout(f):
    return "%s (keepout): %s" % (f["name"], _refusal(f["why"]))


@renders(C.FIXED_ROOM, "item", "copper", "net", "side", "reach_mm")
def _fixed_room(f):
    return ("%s (beside): no place within %.2f mm of its standoff, on its %s side, keeps clear of the planned %s%s: "
            "it stays at the standoff" % (f["item"], f["reach_mm"], f["side"], f["copper"],
                                          " (net %s)" % f["net"] if f["net"] else ""))


@renders(C.FIXED_ROOM_UNSETTLED, "passes")
def _fixed_room_unsettled(f):
    if "arrangements" in f:
        return ("%s: the arrangement it took still changed between the last two of %d passes over the firm items, which took %s "
                "in turn, so what stands beside it was placed against its last pass's choice"
                % (f["item"], f["passes"], ", ".join(f["arrangements"])))
    return ("%s: the copper still moved %s between the last two of %d passes over the firm items, so what stands beside it "
            "was placed against its last plan" % (f["copper"], "by %.3f mm" % f["moved_mm"] if f["moved_mm"] >= 0 else
                                                  "(a different number of segments)", f["passes"]))


# ------------------------------------------------------------------ split cells, setup notes, needs, vias, facts, routes
def split_note(f: dict) -> str:
    """What a split cell's finding says, without the cell's name (the step's note says it as well)."""
    tail = ""
    if f["unjoined"]:
        n = len(f["unjoined"])
        tail = (" (and %d part%s no net inside the cell joins to the others: %s; judge each by what places it: a bypass "
                "capacitor stays with the IC it serves, a sensing part at what it senses)" % (
                    n, "" if n == 1 else "s", ", ".join(f["unjoined"])))
    return ("its parts form %d groups joined only by board-level nets: %s%s. Parts with no close placement requirement in "
            "common may be split into cells of their own." % (
                len(f["groups"]), "; ".join(", ".join(g) for g in f["groups"]), tail))


@renders(C.SPLIT_GROUPS, "cell", "groups", "unjoined")
def _split_groups(f):
    return "%s: %s" % (f["cell"], split_note(f))


@renders(C.SETUP_RULE_NOTE, "variant", "rule", "cell")
def _setup_rule_note(f):
    if f["variant"] == "net":
        return "rule '%s' from the %s cell is not carried: its net %s is not on this board" % (f["rule"], f["cell"], f["net"])
    return "rule '%s' from the %s cell is not carried: its cell %s is not on this board" % (f["rule"], f["cell"], f["within"])


_VIA_VERBS = {"share": "shared", "move": "moved", "route": "re-routed", "leave": "left its pad", "shorten": "shortened",
              "drop": "dropped"}


def vias_note(f: dict) -> str:
    """What carried vias did to give way, without the item's key: "6 GND vias shared, 2 moved up to 0.25 mm, 1 dropped under
    U3", a clause per net, then each field a relay re-laid."""
    return "; ".join(line for _, line, _ in via_lines(f))


def via_lines(f: dict) -> list:
    """`vias_note` a line at a time: [(how many vias the line starts with or None, the line, whether any were dropped)]."""
    said = []
    for net in f["nets"]:
        parts = []
        for part in net["parts"]:
            verb = _VIA_VERBS[part["kind"]]
            n = part["n"]
            if part["kind"] in ("move", "route"):
                verb += (" %.2f mm" if n == 1 else " up to %.2f mm") % part["moved_mm"]
            parts.append(("%d %s via%s %s" % (n, net["net"], "" if n == 1 else "s", verb)) if not parts else "%d %s" % (n, verb))
        held = ", ".join("%s pad %s holds %d of %d" % tuple(h) for h in net["held"])
        said.append((net["parts"][0]["n"] if net["parts"] else None,
                     ", ".join(parts) + (" under %s" % ", ".join(net["under"]) if net["under"] else "") + (" (%s)" % held if held else ""),
                     any(p["kind"] == "drop" for p in net["parts"])))
    for fld in f["fields"]:
        text = "%s field in %s pad %s re-laid by %s, %d vias before, %d after" % (
            fld["net"], fld["pad"][0], fld["pad"][1], fld["way"], fld["before"], fld["after"])
        if fld["after"] < fld["want"]:
            text += " (%d drawn)" % fld["want"]
        said.append((None, text + (" under %s" % ", ".join(fld["under"]) if fld["under"] else ""), False))
    return said


@renders(C.VIAS_GAVE_WAY, "item", "nets", "fields")
def _vias_gave_way(f):
    return "%s: %s" % (f["item"], vias_note(f))


@renders(C.VIAS_DROPPED, "item", "nets", "fields")
def _vias_dropped(f):
    return "%s: %s" % (f["item"], vias_note(f))


@renders(C.NEEDS_OPTION, "item", "option")
def _needs_option(f):
    return "%s: no spot; one would clear with %s" % (f["item"], _refusal(f["option"]))


@renders(C.LABEL_NO_SPOT, "variant", "key", "item")
def _label_no_spot(f):
    from .refusals import EdgeFault
    if f["variant"] == "off_board":
        return "%s: no spot on the board for it beside %s: it is %s" % (
            f["key"], f["item"], EdgeFault(f["edge"]["verdict"], f["edge"]["margin_mm"]))
    if f["variant"] == "line_blocked":
        return "%s: no clear spot beside %s for it and the rest of its line to move to, and %s is in the way" % (
            f["key"], f["item"], ", ".join(f["mine"]))
    return "%s: no clear spot beside %s for it to move to, and %s is in the way" % (f["key"], f["item"], ", ".join(f["mine"]))


@renders(C.ROUTE_DROPPED, "key", "why")
def _route_dropped(f):
    return "adopted route %s dropped: %s; the router routes it again" % (f["key"], _refusal(f["why"]))


@renders(C.ROUTE_WIDTH, "net", "stage", "requested_mm", "delivered_min_mm", "length_under_mm")
def _route_width(f):
    of = " of %.1f mm (%.0f%%)" % (f["length_mm"], 100 * (f.get("share") or 0.0)) if f.get("length_mm") is not None else " mm"
    text = "net %s: %.1f%s of its copper in the %s stage is under the %g mm it was asked, narrowest %g mm" % (
        f["net"], f["length_under_mm"], of, f["stage"], f["requested_mm"], f["delivered_min_mm"])
    if f.get("max_a") is not None:
        text += "; its narrowest copper carries %g A at most" % f["max_a"]
        if f.get("stated_a") is not None:
            text += ", the design states %g A" % f["stated_a"]
    return text


@renders(C.SETUP_LOOKAHEAD, "item", "other", "own", "short_mm", "asked_mm")
def _setup_lookahead(f):
    return ("%s: no spot was left for %s at its limit distance from %s, so the look-ahead was dropped and %s is placed "
            "without it; the best spot for %s left %s %.2f mm short of %.1f mm" % (
                f["item"], f["other"], f["own"], f["own"], f["own"], f["other"], f["short_mm"], f["asked_mm"]))


@renders(C.SETUP_STEP_BUDGET, "item", "judged", "share", "limit")
def _setup_step_budget(f):
    return "%s: %s; it is placed at the best spot found so far" % (f["item"], budget_text(f))


def pass_text(f: dict) -> str:
    """The pass a step was in, from a time finding's facts: "refine pass 2 of 3", "firm pass 1"."""
    from .timecap import pass_phrase
    return pass_phrase(f.get("pass") or "settle", f.get("within"), f.get("firm_pass"))


def _keep_out_item(i: dict, layer: str) -> str:
    if i["kind"] == "pad":
        return "%s pad %s (%s) on %s" % (i["owner"], i["number"], i["net"], layer)
    return "%s %s at (%.2f, %.2f) on %s" % (i["kind"], i["net"], i["at"][0], i["at"][1], layer)


@renders(C.KEEP_OUT_CROSS_LAYER, "net", "distance_mm", "limit_mm", "layers", "away", "pads")
def _keep_out_cross_layer(f):
    return ("keep-out %s: %s is %.2f mm from %s, inside the %g mm keep-out, with no plane between; KiCad's clearance "
            "judges only copper on one layer, so this is not a failed check" % (
                f["net"], _keep_out_item(f["away"], f["layers"][0]), f["distance_mm"],
                _keep_out_item(f["pads"], f["layers"][1]), f["limit_mm"]))


@renders(C.TIME_STEP_SLOW, "item", "elapsed_s", "pass")
def _time_step_slow(f):
    past = " and ".join(t % f[k] for k, t in (("warn_s", "--step-warn %g s"), ("limit_s", "--step-limit %g s")) if f.get(k))
    return "%s: took %.1f s, past %s; it was in the %s when it crossed" % (f["item"], f["elapsed_s"], past, pass_text(f)) + (
        "; no pass was left to stop at, so it finished" if f.get("limit_s") else "")


@renders(C.TIME_STEP_LIMIT, "item", "elapsed_s", "limit_s", "pass", "kept")
def _time_step_limit(f):
    left = ("left unplaced" if f["kept"] == "unplaced" else "placed at the best legal spot its search had found by then")
    return "%s: gave up after %.1f s in the %s (--step-limit %g s) and is %s; the next run searches it again" % (
        f["item"], f["elapsed_s"], pass_text(f), f["limit_s"], left) + (
        "; arrangements not reached: " + ", ".join(f["arrangements"]) if f.get("arrangements") else "")


# ------------------------------------------------------------------ arrangements
def refusal_record_text(r: dict) -> str:
    """One reason an arrangement is not offered (arrangement_run.prove)."""
    form = r["form"]
    if form == "unplaced":
        return "%s is not placed" % r["item"]
    if form == "finding":
        return "%s (%s)" % (r["cause"], r["item"]) if r.get("item") else r["cause"]
    if form == "drc":
        return "DRC %s x%d" % (r["bucket"], r["count"])
    if form == "unconnected":
        return "%d unconnected, the default has %d" % (r["count"], r["default"])
    if form == "verdict":
        return "%s %s failed" % (r["check"], r["item"])
    if form == "nested_cell":
        return "%s, a cell inside the module, stands elsewhere than in the default" % r["item"]
    if form == "escape":
        if r.get("escape"):
            return "%s cannot be laid out with %s as placed" % (r["escape"], r["part"])
        return "a declared escape cannot be laid out with its part as placed"
    if form == "error":
        return "its resolve or proof raised %s: %s" % (r["type"], r["message"])
    if form == "note_chars":
        return "place.arrangement_note_chars = %d leaves no room for its note" % r["chars"]
    return form


def arrangement_row_text(row: dict) -> str:
    """One console line of the module run's arrangements (arrangement_run.lines)."""
    state = row["state"]
    if state == "excluded":
        return "%s: excluded, not laid out%s" % (row["id"], ": " + row["why"] if row["why"] else "")
    if state == "written":
        return "%s: offered, written" % row["id"]
    if state == "offered":
        return "%s: offered%s" % (row["id"], _unit_reasons_text(row.get("reasons", ())))
    if state == "duplicate":
        return "%s: the same as %s, dropped" % (row["id"], row["same_as"])
    return "%s: not offered: %s%s" % (row["id"], "; ".join(refusal_record_text(r) for r in row["refused"]),
                                      _unit_reasons_text(row.get("reasons", ())))


def _unit_reasons_text(reasons) -> str:
    """The reasons of an arrangement's choices (arrangement_run.reasons), after its row: ` - unit: why; unit.option: why;
    item.option: why`."""
    parts = []
    for r in reasons:
        if "item" in r:
            parts.append("%s.%s: %s" % (r["item"], r["option"], r["why"]))
            continue
        if r["unit_why"]:
            parts.append("%s: %s" % (r["unit"], r["unit_why"]))
        if r["why"]:
            parts.append("%s.%s: %s" % (r["unit"], r["option"], r["why"]))
    return " - " + "; ".join(parts) if parts else ""


@renders(C.ARRANGEMENT_LIMIT, "variant", "arrangements", "max_arrangements", "options", "max_options", "excluded")
def _arrangement_limit(f):
    if f["variant"] == "options":
        unit, n = max(f["options"].items(), key=lambda kv: (kv[1], kv[0]))
        return "%s has %d options, over the %d place.arrangement_options_max allows, so only the default is laid out; drop one" % (
            unit, n, f["max_options"])
    after = " once its exclusions leave out %d" % f["excluded"] if f["excluded"] else ""
    return ("this module declares %d arrangements%s, over the %d place.arrangements_max allows, so only the default is laid out; "
            "leave out the combinations that do not matter with board.exclude" % (f["arrangements"], after, f["max_arrangements"]))


@renders(C.ARRANGEMENT_REFUSED, "id", "refused")
def _arrangement_refused(f):
    return "arrangement %s is not offered: %s" % (f["id"], "; ".join(refusal_record_text(r) for r in f["refused"]))


@renders(C.ARRANGEMENT_DUPLICATE, "id", "same_as")
def _arrangement_duplicate(f):
    return "arrangement %s lays out exactly as %s and is dropped" % (f["id"], f["same_as"])


_STALE_WHY = {"version": "its note is of a version this placemat does not read",
              "base": "a note does not match its own digest of the module's default places",
              "offset": "the cell's stamp no longer matches the module's default places",
              "member": "the note names members the cell does not have, or the cell has members the note does not",
              "net": "the note names a net this board does not have",
              "text": "its note text is not whole or does not parse"}


@renders(C.ARRANGEMENT_STALE, "cell", "reason", "ids")
def _arrangement_stale(f):
    ids = ", ".join(f["ids"]) or "its arrangements"
    return "%s: arrangement %s is ignored: %s" % (f["cell"], ids, _STALE_WHY.get(f["reason"], f["reason"]))


@renders(C.ARRANGEMENT_MISSING, "item", "asked", "offered")      # `source` ("lock") is optional, added by the lock
def _arrangement_missing(f):
    if f.get("source") == "lock":
        return ("%s: its lock entry holds arrangement %s, which the module no longer offers (it offers %s); "
                "the entry is released" % (f["item"], ", ".join(f["asked"]), ", ".join(f["offered"]) or "nothing"))
    return "%s: arrangements= names %s, which the module does not offer (it offers %s)" % (
        f["item"], ", ".join(f["asked"]), ", ".join(f["offered"]) or "nothing")


@renders(C.ARRANGEMENT_EXTENT_FIXED, "item", "sides", "protrudes_mm", "alternatives")
def _arrangement_extent_fixed(f):
    return "%s sets the module's extent on the %s side%s (%.1f mm past the next part) and has no alternative" % (
        f["item"], " and ".join(f["sides"]), "s" if len(f["sides"]) > 1 else "", f["protrudes_mm"])


@renders(C.ARRANGEMENT_OPTION_DEAD, "unit", "option", "choice", "refused", "reasons")
def _arrangement_option_dead(f):
    each = "; ".join("%s for %s" % (i, ", ".join(refusal_record_text(r) for r in f["reasons"][i])) for i in f["refused"])
    return "%s is refused in every arrangement that holds it, so the board is never offered it: %s; fix it or drop it" % (
        f["choice"], each)


def facts_reason_text(r: dict) -> str:
    """One reason the board's facts are unconfirmed (facts.unconfirmed_reasons)."""
    reason = r["reason"]
    if reason == "no_record":
        return "no confirmation record yet"
    if reason == "no_via_section":
        return "fab-profile.json has no via section"
    if reason == "no_via_tier":
        return "fab-profile.json's via names no tier for %s" % ", ".join(r["kinds"])
    if reason == "no_min_section":
        return "fab-profile.json has no min section"
    return "the facts have changed since they were last confirmed"


@renders(C.FACTS_UNCONFIRMED, "reasons")
def _facts_unconfirmed(f):
    return "; ".join(facts_reason_text(r) for r in f["reasons"])


# ------------------------------------------------------------------ what a finding is about, and where it is
_SUBJECT_KEYS = ("item", "key", "name", "cell", "link", "net", "ref")


def subject(cause, facts: dict) -> str:
    """What a finding is about, from its facts: the item, the label, the link, the cell or the net it names, with the pin
    where it is about one. Two findings of one cause about different things differ in it, and one finding keeps its
    subject across resolves, so a try is judged by whether the finding it was for is gone."""
    if cause in (C.ESCAPE_CLOSED, C.ESCAPE_WALLED, C.ESCAPE_LANE, C.SETUP_LANE_UNUSED, C.ESCAPE_VIA_UNNEEDED):
        return "%s.%s" % (facts.get("ref") or facts.get("part", ""), facts.get("pin", ""))
    if cause is C.ESCAPE_CROSSED:
        return "%s %s" % (facts["ref"], "/".join(facts["pins"]))
    if cause is C.PAIR_CROSSED:
        return "%s/%s" % (facts["pos"], facts["neg"])
    if cause is C.SETUP_PINS:
        parts = [facts["ref"], facts["key"], facts["entry"], facts["name"]]
        return " ".join(v for i, v in enumerate(parts) if v and v not in parts[:i])
    if cause is C.PINS_REMAP:
        return " ".join(facts["refs"])
    if cause is C.LINK_OVER:
        return facts["link"]
    if cause is C.ARRANGEMENT_OPTION_DEAD:
        return facts["choice"]
    for k in _SUBJECT_KEYS:
        v = facts.get(k)
        if isinstance(v, str) and v:
            return v
    return ""


_PADS = {
    C.LINK_OVER: lambda f: [[f["a"]["ref"], f["a"]["pad"]], [f["b"]["ref"], f["b"]["pad"]]],
    C.ESCAPE_CLOSED: lambda f: [[f["ref"], f["pin"]]],
    C.ESCAPE_WALLED: lambda f: [[f["ref"], f["pin"]]],
    C.ESCAPE_LANE: lambda f: [[f["ref"], f["pin"]]],
    C.SETUP_LANE_UNUSED: lambda f: [[f["ref"], f["pin"]]],
    C.ESCAPE_VIA_UNNEEDED: lambda f: [[f["ref"], f["pin"]]],
    C.ESCAPE_CROSSED: lambda f: [[f["ref"], p] for p in f["pins"]],
}


def _refs_in_facts(v, known: set, out: list) -> None:
    """The strings in `v` (facts, nested) that are refdes the plan placed, in the order met."""
    if isinstance(v, str):
        if v in known and v not in out:
            out.append(v)
    elif isinstance(v, dict):
        for x in v.values():
            _refs_in_facts(x, known, out)
    elif isinstance(v, (list, tuple)):
        for x in v:
            _refs_in_facts(x, known, out)


def _first_at(v):
    if isinstance(v, dict):
        at = v.get("at")
        if isinstance(at, (list, tuple)) and len(at) == 2 and all(isinstance(x, (int, float)) for x in at):
            return [float(at[0]), float(at[1])]
        for x in v.values():
            found = _first_at(x)
            if found is not None:
                return found
    elif isinstance(v, (list, tuple)):
        for x in v:
            found = _first_at(x)
            if found is not None:
                return found
    return None


def locate(cause, facts: dict, refs) -> dict:
    """Where a finding is and which parts it concerns, for a preview: {"at": [x, y] or None, "refs": [placed refdes the
    facts name], "pads": [[ref, pad], ...]}. `at` is the first point the facts carry."""
    found: list = []
    _refs_in_facts(facts, set(refs), found)
    pads = _PADS[cause](facts) if cause in _PADS else []
    return {"at": _first_at(facts), "refs": found, "pads": [list(p) for p in pads if p[0] in refs]}


def pocket_took_text(p: dict) -> str:
    """What a seeded item that took a pocket says of it: its size, where, how far from the seed, and the face it took if
    that is not the one it asked for."""
    return "took the pocket %.1f x %.1f at (%.1f, %.1f), %.1f mm from the seed%s" % (
        p["w_mm"], p["h_mm"], p["at"][0], p["at"][1], p["seed_mm"], ", on the %s face" % p["face"] if p["face"] else "")


@renders(C.SETUP_CENTRE_FLAG_DEFAULT, "item")
def _setup_centre_flag_default(f):
    return "%s: coordinates=False is the default: leave it out" % f["item"]


# ------------------------------------------------------------------ schema versions of causes whose facts have changed
FACTS_V[C.FIXED_ROOM_UNSETTLED] = 2     # a firm cell whose arrangement did not settle: item and arrangements, not copper
FACTS_V[C.ARRANGEMENT_LIMIT] = 2        # excluded: how many combinations the module's exclusions leave out
FACTS_V[C.PINS_REMAP] = 3               # 2: controlled impedances' length, groups' spread, cohesion and landing;
                                        # 3: steps and budget_steps in place of budget_ms
