"""Each cause renders the sentence it has always had, from its facts; the facts survive JSON and the reuse record."""
import json

import pytest

from placemat import finding_text as ft, reuse
from placemat.findings import Finding, FindingCause as C
from placemat.refusals import Code, Refusal, ReservedBy

EDGE = Refusal(Code.EDGE, what="body", box=[1.0, 2.0, 3.0, 4.0], verdict="outside", margin_mm=0.0).to_json()
NEAR = Refusal(Code.COPPER_NEAR, form="part", what="pad", who=["R1", ""], net="A", gap_mm=0.05, need_mm=0.2,
               other={"net": "B", "who": ["R2", ""]}, layers=["F.Cu"]).to_json()
SITE = Refusal(Code.SITE_KEEPOUT).to_json()
OWNER = {"form": "who", "name": "R1"}
LINK = {"link": "A.1>B.2", "a": {"key": "a", "ref": "A", "pad": "1"}, "b": {"key": "b", "ref": "B", "pad": "2"},
        "achieved_mm": 3.0, "limit_mm": 2.0, "why": ""}
BLAME = [{"form": "kind", "count": 3, "label": "courtyard", "owners": [{"owner": OWNER, "faces": "front", "count": 3}]}]

SAMPLES = [
    (C.UNPLACED_SEARCH, {"item": "c4", "radius_mm": 3.0, "at": [10.0, 20.0], "blame": BLAME, "pocket_tried": 2,
                         "room_lost": {"gone": ["u1"], "kept": []}},
     "c4: no legal location within 3.0 mm of (10.00, 20.00) (courtyard x3: R1 front face x3); no pocket took it (2 tried); "
     "see: no room was left for it when u1 was placed"),
    (C.UNPLACED_SEARCH, {"item": "c4", "radius_mm": 3.0, "at": [10.0, 20.0], "blame": BLAME,
                         "budget": {"judged": 5000, "share": 0.1234, "limit": 5000}},
     "c4: no legal location found within 3.0 mm of (10.00, 20.00) (courtyard x3: R1 front face x3); the search stopped at its "
     "budget of 5000 candidates, with 12.3% of the search area covered"),
    (C.UNPLACED_POCKET, {"item": "c4", "variant": "tried", "w_mm": 4.0, "h_mm": 2.0, "face": "front", "tried": 0, "riders": []},
     "c4: no pocket fits its 4.0 x 2.0 envelope on the front face (0 pocket(s) tried)"),
    (C.UNPLACED_POCKET, {"item": "c4", "variant": "any_rotation", "w_mm": 4.0, "h_mm": 2.0, "face": "front or back"},
     "c4: no pocket fits its 4.0 x 2.0 envelope on the front or back face at any rotation asked for"),
    (C.UNPLACED_SLIDE, {"item": "j1", "where": {"form": "edge", "edge": "north"}, "counts": [["edge", 4]], "riders": []},
     "j1: no room anywhere along the north edge (edge x4)"),
    (C.UNPLACED_SLIDE, {"item": "j1", "where": {"form": "line", "axis": "x", "at_mm": 5.0, "toward": "south"},
                        "counts": [["body", 1]], "riders": []},
     "j1: no room anywhere on the line x = 5.00; as far south as it is legal (body x1)"),
    (C.UNPLACED_BLOCK, {"item": "ldo", "variant": "scan", "radius_mm": 3.0, "at": [1.0, 2.0], "counts": [["copper", 5]]},
     "ldo: no legal spot within 3.0 mm of (1.00, 2.00) (copper x5)"),
    (C.UNPLACED_BEARING, {"item": "j1", "turns": 72, "counts": [["edge", 72]]},
     "j1: no bearing of 72 tried leaves it legal on its point (edge x72)"),
    (C.UNPLACED_RIDES, {"item": "nt", "variant": "rode", "rider_of": "c"}, "nt: rides c, which found no place"),
    (C.SETUP_CENTRE_FLAG_DEFAULT, {"item": "u1"}, "u1: coordinates=False is the default: leave it out"),
    (C.LINK_OVER, LINK, "link A.1 to B.2 is 3.00 mm, over its 2.00 mm limit"),
    (C.FIXED_PART, {"item": "u1", "freedom": "fixed", "why": EDGE}, "u1 (fixed): body box 1.00,2.00..3.00,4.00 is outside the board"),
    (C.FIXED_CUTOUT, {"name": "slot", "why": Refusal(Code.CUTOUT_OUTSIDE).to_json()}, "slot (cutout): reaches outside the board"),
    (C.FIXED_KEEPOUT, {"name": "ant", "why": Refusal(Code.CUTOUT_NOWHERE, nearest=None).to_json()},
     "ant (keepout): has nowhere legal to go: nowhere on the board"),
    (C.FIXED_ROOM, {"item": "c1", "copper": "track SIG", "net": "SIG", "side": "north", "reach_mm": 2.0},
     "c1 (beside): no place within 2.00 mm of its standoff, on its north side, keeps clear of the planned track SIG (net SIG): "
     "it stays at the standoff"),
    (C.FIXED_ROOM_UNSETTLED, {"copper": "track SIG", "moved_mm": 0.2, "passes": 4},
     "track SIG: the copper still moved by 0.200 mm between the last two of 4 passes over the firm items, so what stands beside "
     "it was placed against its last plan"),
    (C.FIXED_ROOM_UNSETTLED, {"item": "mod", "arrangements": ["c_in.a", "c_in.b", "default"], "passes": 4},
     "mod: the arrangement it took still changed between the last two of 4 passes over the firm items, which took c_in.a, "
     "c_in.b, default in turn, so what stands beside it was placed against its last pass's choice"),
    (C.COPPER_KEEPOUT, {"word": "track", "net": "A", "keepout": "ant", "why": "an antenna"},
     "track A crosses keepout 'ant' (an antenna): a track goes exactly where it is put, so move it, reshape it, or name its "
     "net in the keepout's allow="),
    (C.COPPER_CROSS, {"variant": "tracks", "net_a": "A", "net_b": "B", "layer": "F.Cu", "at": [1.0, 2.0], "left_out": "track A"},
     "A and B cross on F.Cu at (1.00, 2.00) and neither may bridge; track A is not drawn"),
    (C.COPPER_MEETS, {"net": "A", "hit": NEAR, "chamfer_at": [1.0, 2.0]},
     "copper A: R1 pad A is 0.05 mm from B copper on F.Cu (needs 0.20); the 45 of its chamfer at (1.00, 2.00); "
     "a smaller chamfer= there keeps clear"),
    (C.COPPER_NOT_DRAWN, {"variant": "via_lost", "track": "A", "lost": ["via A"]},
     "track A: its end on via A is not drawn, because that via found no spot"),
    (C.COPPER_NOT_DRAWN, {"variant": "through", "net": "A", "met": {"form": "via", "net": "B"}},
     "track A: not drawn, it would run through a B via"),
    (C.COPPER_NOT_DRAWN, {"variant": "pour_close", "net": "A", "between": [["pad", "U1", "1"], ["via", 1.0, 2.0]], "noun": "member",
                          "what": {"form": "unplated", "who": ["J1", ""]}},
     "pour A: J1's unplated hole is within its clearance of member U1.1 and via at (1.00, 2.00), so no pour can hold the "
     "member clear; the pour is not drawn"),
    (C.COPPER_CORNER, {"net": "A", "edge": "NE", "names": ["R1", "R2"], "near_mm": 0.1, "need_mm": 0.2},
     "track A: the points either side of its 45 past the NE corner of R1, R2 allow no 45 through it; the track passes that "
     "corner at 0.100 mm, under the 0.200 mm clearance"),
    (C.COPPER_NOTE, {"variant": "waypoint", "net": "A"},
     "track A: a waypoint steers it into another net's pad; drawn pad to pad it clears, so drop the waypoint(s) unless the "
     "route must go there"),
    (C.COPPER_STITCH, {"variant": "left_out", "net": "GND", "left_out": [[1.0, 2.0, SITE]]},
     "stitch GND: 1 via(s) outside the region left out: (1.00, 2.00) inside a keepout, which forbids vias"),
    (C.LABEL_SITS_ON, {"item": "j1", "text": "IN", "hits": ["R1"]}, "label j1 IN: sits on R1"),
    (C.LABEL_NO_SPOT, {"variant": "off_board", "key": "label j1 IN", "item": "j1", "edge": {"verdict": "outside", "margin_mm": 0.2}},
     "label j1 IN: no spot on the board for it beside j1: it is outside the board"),
    (C.LABEL_NO_SPOT, {"variant": "blocked", "key": "label j1 IN", "item": "j1", "mine": ["R1"]},
     "label j1 IN: no clear spot beside j1 for it to move to, and R1 is in the way"),
    (C.LABEL_NOT_DRAWN, {"item": "j1", "text": "IN", "waiting": "R1"}, "label j1 IN: not drawn: R1 found no place"),
    (C.LABEL_CELL_EDGE, {"cell": "debug", "text": "TX", "edge": "cutout", "cutout": "vent", "gap_mm": 0.0, "need_mm": 0.2},
     "cell debug label TX: 0.00 mm from cutout vent, under the 0.20 mm silk clearance"),
    (C.LABEL_CELL_EDGE, {"cell": "debug", "text": "TX", "edge": "outline", "cutout": None, "gap_mm": 0.1, "need_mm": 0.2},
     "cell debug label TX: 0.10 mm from the board outline, under the 0.20 mm silk clearance"),
    (C.ESCAPE_CROSSED, {"ref": "U1", "pins": ["1", "2"], "targets": [["J1", "A"], ["J2", "B"]]}, "U1 pins 1/2: J1 A crosses J2 B"),
    (C.ESCAPE_CLOSED, {"ref": "U1", "pin": "3", "net": "A", "joins": ["J1"], "by": [OWNER]},
     "U1 pin 3 (A): closed toward J1 by R1"),
    (C.ESCAPE_WALLED, {"variant": "walled", "ref": "U1", "pin": "3", "net": "A", "by": []}, "U1 pin 3 (A): walled off by copper"),
    (C.ESCAPE_LANE, {"ref": "U1", "pin": "3", "net": "A", "blocked": [Refusal(Code.LANE_PAD, pin="4", gap_mm=0.1, need_mm=0.2).to_json()]},
     "U1 pin 3 (A): its lane is blocked by pad 4 of its own part, 0.100 mm off (needs 0.200)"),
    (C.ESCAPE_VIA_UNNEEDED, {"ref": "U1", "part": "u1", "pin": "3", "net": "A", "layers": ["F.Cu"],
                             "via": {"kind": "lane", "at": [1.0, 2.0], "key": ""}},
     "U1 pin 3 (A): the via at (1.00, 2.00) that ends its lane is not needed: the lane reaches the frame's edge on F.Cu "
     "without it, so it can end there for the parent board's router; take the pin out of the escape's vias="),
    (C.ESCAPE_VIA_UNNEEDED, {"ref": "U1", "part": "u1", "pin": "3", "net": "A", "layers": ["F.Cu"],
                             "via": {"kind": "via", "at": [1.0, 2.0], "key": "via A#4"}},
     "U1 pin 3 (A): via A at (1.00, 2.00), on its lane's copper, is not needed: the lane reaches the frame's edge on F.Cu "
     "without it, so it can end there for the parent board's router; remove the board.via"),
    (C.PAIR_CROSSED, {"pos": "P", "neg": "N", "parts": ["R1", "R2"]},
     "P/N cross between R1, R2: swap two interchangeable parts on the pair, or turn a part whose pinout is mirrored 180 degrees"),
    (C.SETUP_UNDECLARED, {"item": "c1", "ref": "C1"}, "c1 (C1): no declaration places it, so it stays where the generator put it"),
    (C.SETUP_LANE_UNUSED, {"ref": "U1", "pin": "3"},
     "U1 pin 3: its lane is reserved and no track begins with it, so its room is kept for nothing"),
    (C.SETUP_ACCEPT, {"variant": "unmatched", "check": "keep-out", "subject": "A"},
     "accept keep-out A: no verdict by that check and subject on this board"),
    (C.SETUP_RULE_NOTE, {"variant": "net", "rule": "r", "cell": "k", "net": "N"},
     "rule 'r' from the k cell is not carried: its net N is not on this board"),
    (C.SETUP_LOOKAHEAD, {"item": "u1", "other": "u2", "own": "R1", "short_mm": 0.5, "asked_mm": 2.0},
     "u1: no spot was left for u2 at its limit distance from R1, so the look-ahead was dropped and R1 is placed without it; the "
     "best spot for R1 left u2 0.50 mm short of 2.0 mm"),
    (C.SETUP_STEP_BUDGET, {"item": "u1", "judged": 20000, "share": 0.05, "limit": 20000},
     "u1: the search stopped at its budget of 20000 candidates, with 5.0% of the search area covered; it is placed at the best "
     "spot found so far"),
    (C.SETUP_PCBNEW, {"variant": "current", "net": "A"},
     "pour A: reach=Reach.CURRENT needs KiCad's pcbnew at plan time, for its polygon booleans; the pour is not drawn"),
    (C.SETUP_NATIVE, {"in_use": False, "reason": "version_mismatch", "placemat_version": "0.98.0", "native_version": "0.97.0", "detail": ""},
     "placemat_native 0.97.0 does not match placemat 0.98.0, so the pure Python path runs: results are the same, 5-10x slower on a "
     "large board; rebuild it from this checkout's native/ (uv pip install -e \".[native]\")"),
    (C.SETUP_PAIR_LAYERS, {"key": "D_P/D_N", "variant": "layer_missing", "layers": ["In4.Cu", "B.Cu"], "missing": ["In4.Cu"],
                           "board_layers": ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]},
     "route.pair_layers D_P/D_N: names In4.Cu, which this board does not have (it has F.Cu, In1.Cu, In2.Cu, B.Cu); the pair "
     "routes on the route's own layers"),
    (C.SETUP_PAIR_LAYERS, {"key": "Fast", "variant": "no_pair", "layers": ["B.Cu"], "missing": [], "board_layers": ["F.Cu", "B.Cu"]},
     "route.pair_layers Fast: no differential pair on this board has those two nets or that net class; the entry is not used"),
    (C.SETUP_NET_HALO, {"variant": "trapped", "net": "SW", "halo_mm": 2.0, "ref": "U3", "number": "2", "pad_net": "FB",
                        "gap_mm": 0.4, "reach_mm": 0.6, "needed_mm": 2.1, "short_mm": 1.5},
     "FB pad U3.2 is inside SW's 2.00 mm halo; its copper ends 0.60 mm away where a track leaving it needs 2.10 mm, 1.50 mm "
     "short: draw its escape out past the halo in the module (a longer run= on its board.escape), or give SW a smaller halo"),
    (C.SETUP_NET_HALO, {"variant": "no_net", "net": "GONE", "halo_mm": 1.0},
     "route.net_halos GONE: no net of that name on this board; the entry is not used"),
    (C.SETUP_NET_HALO, {"variant": "open", "net": "SW", "halo_mm": 2.0, "open_items": 1},
     "SW is open (1 item(s)) and routed with the other nets: the router spaces every net of that pass 2.00 mm from all "
     "copper, not only from SW; draw SW whole in the module, or route it alone as a `[route] islands` net"),
    (C.ROUTE_DROPPED, {"key": "X","why": Refusal(Code.ROUTE_END, at=[1.0, 2.0]).to_json()},
     "adopted route X dropped: its end at (1.00, 2.00) no longer meets the net's other copper; the router routes it again"),
    (C.ROUTE_WIDTH, {"net": "V", "stage": "islands", "requested_mm": 1.37, "delivered_min_mm": 0.16, "length_under_mm": 16.61,
                     "length_mm": 17.24, "share": 0.9636, "declared": True, "max_a": 0.45, "bottleneck_mm": 0.1, "stated_a": 3.0},
     "net V: 16.6 of 17.2 mm (96%) of its copper in the islands stage is under the 1.37 mm it was asked, narrowest 0.16 mm; its "
     "narrowest copper carries 0.45 A at most, the design states 3 A"),
    (C.ROUTE_WIDTH, {"net": "V", "stage": "main", "requested_mm": 0.5, "delivered_min_mm": 0.2, "length_under_mm": 3.0,
                     "length_mm": None, "share": None, "declared": False, "max_a": None, "bottleneck_mm": None, "stated_a": None},
     "net V: 3.0 mm of its copper in the main stage is under the 0.5 mm it was asked, narrowest 0.2 mm"),
    (C.VIAS_GAVE_WAY, {"item": "m", "nets": [{"net": "SIG", "parts": [{"kind": "move", "n": 1, "moved_mm": 0.25}],
                                              "under": ["R9"], "held": []}], "fields": []},
     "m: 1 SIG via moved 0.25 mm under R9"),
    (C.FAB_MINIMUM, {"net_class": "P", "what": "track width", "value_mm": 0.08, "minimum_mm": 0.1, "key": "track_mm"},
     "net class P: track width 0.08 mm is below the fab's minimum 0.1 mm (fab-profile.json min.track_mm)"),
    (C.FACTS_UNCONFIRMED, {"reasons": [{"reason": "no_record"}]}, "no confirmation record yet"),
    (C.NEEDS_OPTION, {"item": "c1", "option": Refusal(Code.OPTION_VIA, via="blind", from_layer="F.Cu", to_layer="In2.Cu").to_json()},
     "c1: no spot; one would clear with a blind via shortened to F-In2 (via.blind is if-needed in fab-profile.json)"),
    (C.SPLIT_GROUPS, {"cell": "k", "groups": [["R1", "R2"], ["C1", "C2"]], "unjoined": []},
     "k: its parts form 2 groups joined only by board-level nets: R1, R2; C1, C2. Parts with no close placement requirement in "
     "common may be split into cells of their own."),
    (C.KEEP_OUT_CROSS_LAYER, {"net": "SW", "distance_mm": 0.7, "limit_mm": 2.0, "layers": ["F.Cu", "B.Cu"],
                              "away": {"kind": "pad", "owner": "L1", "number": "1", "net": "SW", "at": [18.6, 13.0]},
                              "pads": {"kind": "via", "owner": None, "number": None, "net": "FB", "at": [18.6, 15.0]}},
     "keep-out SW: L1 pad 1 (SW) on F.Cu is 0.70 mm from via FB at (18.60, 15.00) on B.Cu, inside the 2 mm keep-out, with no "
     "plane between; KiCad's clearance judges only copper on one layer, so this is not a failed check"),
    (C.TIME_STEP_SLOW, {"item": "u1", "elapsed_s": 45.2, "warn_s": 30.0, "limit_s": None, "warned_at_s": 30.1, "pass": "refine",
                        "within": [2, 3], "stage": "refine", "firm_pass": None},
     "u1: took 45.2 s, past --step-warn 30 s; it was in the refine pass 2 of 3 when it crossed"),
    (C.TIME_STEP_LIMIT, {"item": "u1", "elapsed_s": 60.4, "limit_s": 60.0, "pass": "coarse", "within": None, "stage": "coarse",
                         "firm_pass": None, "kept": "unplaced"},
     "u1: gave up after 60.4 s in the coarse pass (--step-limit 60 s) and is left unplaced; the next run searches it again"),
    (C.SETUP_PINS, {"ref": "U1", "key": "Pm.PinAllow", "entry": "ADC0:1-4", "code": "no_net", "name": "ADC0", "held_net": "",
                    "held_pin": ""},
     "U1: Pm.PinAllow names net ADC0, which no pin of U1 carries; the study runs without ADC0:1-4"),
    (C.SETUP_PINS, {"ref": "U1", "key": "", "entry": "", "code": "no_legal_pin", "name": "A", "held_net": "D",
                    "held_pin": "4"},
     "U1: net A may take only pin 4, which net D holds; U1 is not studied"),
    (C.PINS_REMAP, {"ref": "U1", "refs": ["U1", "U2"], "at": [10.0, 10.0], "first_map": True, "budget_out": True,
                    "budget_ms": 200, "searched": 9, "of": 16, "best": 1, "routed": ["A"],
                    "present": {"total": 20.0, "weighted": 12.0, "length_mm": 40.0, "bend_deg": 90.0},
                    "rotations": [{"total": 19.0, "weighted": 12.0, "length_mm": 36.0, "bend_deg": 90.0,
                                   "turns": [{"ref": "U1", "turn_deg": 0.0, "rotation_deg": 0.0, "face": "front", "flip": False},
                                             {"ref": "U2", "turn_deg": 0.0, "rotation_deg": 0.0, "face": "front", "flip": False}]},
                                  {"total": 8.0, "weighted": 4.0, "length_mm": 38.0, "bend_deg": 90.0,
                                   "turns": [{"ref": "U1", "turn_deg": 90.0, "rotation_deg": 90.0, "face": "front", "flip": False},
                                             {"ref": "U2", "turn_deg": 180.0, "rotation_deg": 180.0, "face": "back", "flip": True}]}],
                    "present_breaks": [{"ref": "U2", "net": "B", "pin": "7", "rule": "Pm.PinDeny"}]},
     "U1 and U2: a pin map with 4.0 mm less airwire exists at their present rotations; at U1 at 90 degrees and U2 at 180 "
     "degrees on the back, 8 fewer weighted crossings; 1 of the nets it moves has copper now: A; the study stopped at its "
     "200 ms after 9 of 16 poses"),
    (C.PINS_REMAP, {"ref": "U1", "refs": ["U1"], "at": [10.0, 10.0], "first_map": True, "budget_out": False,
                    "budget_ms": 100, "searched": 4, "of": 4, "best": 2, "routed": ["A", "B"], "present_breaks": [],
                    "present": {"total": 20.0, "weighted": 12.0, "length_mm": 40.0, "bend_deg": 90.0},
                    "rotations": [{"total": 20.0, "weighted": 12.0, "length_mm": 40.0, "bend_deg": 90.0,
                                   "turns": [{"ref": "U1", "turn_deg": 0.0, "rotation_deg": 0.0, "face": "front", "flip": False}]},
                                  {"total": 20.0, "weighted": 12.0, "length_mm": 40.0, "bend_deg": 90.0,
                                   "turns": [{"ref": "U1", "turn_deg": 90.0, "rotation_deg": 90.0, "face": "front", "flip": False}]},
                                  {"total": 15.0, "weighted": 13.0, "length_mm": 20.0, "bend_deg": 120.0,
                                   "turns": [{"ref": "U1", "turn_deg": 180.0, "rotation_deg": 180.0, "face": "front", "flip": False}]}]},
     "U1: no better pin map at its present rotation; at 180 degrees, 20.0 mm less airwire and 1 more weighted crossing; "
     "2 of the nets it moves have copper now: A, B"),
    (C.SETUP_PINS, {"ref": "U1", "key": "Pm.PinDeny", "entry": "", "code": "present_breaks", "name": "A", "held_net": "",
                    "held_pin": "", "pin": "1", "rule": "Pm.PinDeny"},
     "U1: net A stands on pin 1, against its Pm.PinDeny; the capture breaks its own rule"),
    (C.SETUP_PINS, {"ref": "", "key": "", "entry": "", "code": "study_failed", "name": "", "held_net": "", "held_pin": "",
                    "type": "RuntimeError", "message": "boom"},
     "the pin map study failed with RuntimeError: boom; this resolve has no pin map findings"),
    (C.ARRANGEMENT_LIMIT, {"variant": "arrangements", "arrangements": 12, "max_arrangements": 8,
                           "options": {"c_in": 3, "r_pull": 2, "pair": 2}, "max_options": 4, "excluded": 0},
     "this module declares 12 arrangements, over the 8 place.arrangements_max allows, so only the default is laid out; "
     "leave out the combinations that do not matter with board.exclude"),
    (C.ARRANGEMENT_LIMIT, {"variant": "arrangements", "arrangements": 10, "max_arrangements": 8,
                           "options": {"c_in": 3, "r_pull": 2, "pair": 2}, "max_options": 4, "excluded": 2},
     "this module declares 10 arrangements once its exclusions leave out 2, over the 8 place.arrangements_max allows, so only "
     "the default is laid out; leave out the combinations that do not matter with board.exclude"),
    (C.ARRANGEMENT_LIMIT, {"variant": "options", "arrangements": 6, "max_arrangements": 8,
                           "options": {"c_in": 5}, "max_options": 4, "excluded": 0},
     "c_in has 5 options, over the 4 place.arrangement_options_max allows, so only the default is laid out; drop one"),
    (C.ARRANGEMENT_OPTION_DEAD, {"unit": "pair", "option": "upright", "choice": "pair.upright",
                                 "refused": ["pair.upright", "pair.upright+r_far.turned"],
                                 "reasons": {"pair.upright": [{"form": "drc", "bucket": "clearance", "count": 2}],
                                             "pair.upright+r_far.turned": [{"form": "unplaced", "item": "r_far"}]}},
     "pair.upright is refused in every arrangement that holds it, so the board is never offered it: pair.upright for DRC "
     "clearance x2; pair.upright+r_far.turned for r_far is not placed; fix it or drop it"),
    (C.ARRANGEMENT_REFUSED, {"id": "mirrored", "refused": [{"form": "drc", "bucket": "clearance", "count": 2},
                                                           {"form": "verdict", "check": "hot-loop", "item": "c_in"}]},
     "arrangement mirrored is not offered: DRC clearance x2; hot-loop c_in failed"),
    (C.ARRANGEMENT_DUPLICATE, {"id": "c_in.same", "same_as": "default"},
     "arrangement c_in.same lays out exactly as default and is dropped"),
    (C.ARRANGEMENT_STALE, {"cell": "mod", "reason": "base", "ids": ["c_in.east"]},
     "mod: arrangement c_in.east is ignored: a note does not match its own digest of the module's default places"),
    (C.ARRANGEMENT_MISSING, {"item": "mod", "asked": ["c_in.west"], "offered": ["default", "c_in.east"]},
     "mod: arrangements= names c_in.west, which the module does not offer (it offers default, c_in.east)"),
    (C.ARRANGEMENT_MISSING, {"item": "mod", "asked": ["c_in.west"], "offered": ["default"], "source": "lock"},
     "mod: its lock entry holds arrangement c_in.west, which the module no longer offers (it offers default); "
     "the entry is released"),
    (C.ARRANGEMENT_EXTENT_FIXED, {"item": "c_bulk", "sides": ["east", "north"], "protrudes_mm": 1.8, "alternatives": True},
     "c_bulk sets the module's extent on the east and north sides (1.8 mm past the next part) and has no alternative"),
]


@pytest.mark.parametrize("cause, facts, text", SAMPLES, ids=[s[0].value for s in SAMPLES])
def test_a_cause_renders_its_sentence_from_its_facts(cause, facts, text):
    f = Finding(cause, facts)
    assert str(f) == text
    assert json.loads(json.dumps(f.facts)) == f.facts                      # the facts are JSON
    g = reuse.finding_from_json(json.loads(json.dumps(reuse.finding_to_json(f))))
    assert g == f and g.cause is cause and g.facts == f.facts


def test_every_cause_has_a_sample():
    """Four setup causes are pinned by the tests of the situations that raise them (pitch, web, frame reach, a lost layer)."""
    missing = {c for c in C} - {s[0] for s in SAMPLES}
    assert missing == {C.SETUP_PITCH, C.SETUP_WEB, C.SETUP_FRAME_REACH, C.SETUP_LAYER_LOST, C.VIAS_DROPPED}


def test_a_changed_facts_version_changes_the_schemas_digest(monkeypatch):
    before = ft.schemas_digest()
    monkeypatch.setitem(ft.FACTS_V, C.LINK_OVER, 2)
    assert ft.schemas_digest() != before


def test_a_stored_finding_of_another_version_is_not_replayed():
    stored = reuse.finding_to_json(Finding(C.SETUP_UNDECLARED, {"item": "c1", "ref": "C1"}))
    stored[3] = 99
    with pytest.raises(ValueError):
        reuse.finding_from_json(stored)


def test_a_reservation_is_named_by_what_made_it():
    assert str(ReservedBy("keepout", "ant", "a note")) == "keepout 'ant' (a note)"
    assert str(ReservedBy("label", "j1 IN", item="j1")) == "label j1 IN"
    assert str(ReservedBy("fanout", "U1", side="north")) == "fanout of U1 (north side)"
    assert str(ReservedBy("push", "M1", "why", limit=0.3, radius_mm=29.7)) == "push from M1 (limit 0.3 at 29.7 mm): why"
