"""Every behavioural constant placemat has, and where a project may set it.

One `placemat.toml` per project (or per board), found by walking up from the
board directory and merged nearest-wins. Precedence is built-in default, then
the file, then a CLI flag. An attribute is named for its TOML home: `[place]
step` is `place_step`, so a section and a key are derived from the name and
never mapped by hand.

`Settings` is carried by the objects that have one - `Board.settings`,
`Occupancy.settings` - so nothing on the placement hot path looks a value up
per candidate. The deep geometry helpers that are reached through frozen value
objects read `active()` instead, bound for a run by `bind()`, the same scoped
binding `context.bind` uses for the board.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import MISSING, dataclass, field, fields, replace
import json
import math
from pathlib import Path
import re
import tomllib

# The violation classes a board is judged by. A project may say otherwise.
DEFAULT_REAL_KINDS = ("clearance", "shorting_items", "track_width", "annular_width",
                      "hole_clearance", "hole_to_hole", "courtyards_overlap",
                      "copper_edge_clearance")
DEFAULT_OUTSTANDING_KINDS = ("via_dangling", "track_dangling", "isolated_copper")
# Problems in the footprints themselves. They do not block a board, but they
# make every extent placemat computes for those parts unreliable, so they get
# a bucket of their own rather than going into `other` where nobody looks.
DEFAULT_FOOTPRINT_KINDS = ("lib_footprint_issues", "lib_footprint_mismatch",
                           "malformed_courtyard", "padstack")

FILENAME = "placemat.toml"

# What a setting's unit may be (data about it, shown in the docs and in `placemat settings --example`).
UNITS = frozenset((
    "mm", "steps", "degrees", "nm", "deg C", "ohm m", "W/(m K)", "seconds", "ms", "pixels", "px/mm", "per second", "count", "ratio",
    "share", "fraction", "probability", "weight", "multiplier", "factor", "exponent", "residual", "cost", "track widths",
    "bool", "choice", "list", "table", "text", "path", "command", "port"))

# The sections: a name and what the settings under it govern, for the docs and the example file.
SECTIONS = {
    "rank": "how searched items are ordered: the weights of what makes one go first",
    "place": "the placement search: radii, steps, rotations, escapes, carried vias and how they give way",
    "copper": "copper a script declares: chamfers and arcs, bridges, planes, pours, taps",
    "write": "how the board is written through pcbnew: groups and keepout drawings",
    "label": "silkscreen labels: size, stroke and where they slide",
    "geometry": "how curves and the spatial index are approximated",
    "check": "`placemat check`: the temperature, keep-out and current-path rules",
    "parts": "what a placed part must carry to be orderable",
    "drc": "how KiCad's DRC violations are sorted into buckets and judged",
    "explore": "the time-boxed search of the placer's own choices (`--explore`): variation, workers, checkpoint, stopping rules",
    "pins": "the pin map study: what may move on a part with a `Pm.PinPool`, how a map is scored and searched, and when it is a finding",
    "route": "routing a copy of the board with KiCadRoutingTools",
    "run": "how long `placemat run` and `preview` may take: a cap on the command and on one step (off by default; a flag of the same name wins), and whether a run's last stages work alongside each other. Not part of a run's id",
    "timeout": "how long each external tool may run before it is given up on",
    "noise": "KiCad stderr lines to suppress, added to the built-ins",
    "best": "judging a run against the best of its family: how much a measure may move before it counts",
    "score": "what each thing that can go wrong costs a run, in millimetres of wire: the run score and the search's own prices",
    "solve": "the global pre-solve that gives searched items their starting hints",
    "preview": "`placemat preview`: SVG to PNG conversion and the image's size",
    "cleanup": "the pass after the searched tier that moves and swaps parts to shorten wire",
    "studio": "`placemat studio`'s server and watcher (not part of a run's id)",
    "facts": "placemat's own record of confirmed board facts (written by `placemat facts --confirm`; not for editing)",
}


def S(default=MISSING, unit: str = "", doc: str = "", *, factory=None):
    """A setting's field: its default, its unit (one of UNITS) and what it means, as data."""
    meta = {"unit": unit, "doc": doc}
    if factory is not None:
        return field(default_factory=factory, metadata=meta)
    return field(default=default, metadata=meta)


@dataclass(frozen=True)
class Settings:
    """Resolved settings for one run. Frozen: a run is judged by one set."""
    rank_area_weight: float = S(0.7, "weight",
        "weight on courtyard area when ordering searched items")
    rank_pins_weight: float = S(0.3, "weight",
        "weight on pin count when ordering searched items")
    place_radius: float = S(3.0, "mm",
        "a search's default radius")
    place_step: float = S(0.2, "mm",
        "a search's default step")
    place_envelope: str = S("courtyard", "choice",
        "what a part claims against another: `courtyard` (its courtyard and pads), `physical` (its pads, mask openings, silk and body, each at the board's own gap), or `union` (both)")
    place_rotations: str = S("all", "choice",
        "a searched part with no `rotation=` or `rotations=`: `all` four rotations, or only its `declared` one")
    place_bearing_step: float = S(5.0, "degrees",
        "degrees between the turns of `rotations=Turns.ANY`")
    place_tangent_bin: float = S(10.0, "degrees",
        "degrees of bearing a `Turns.TANGENT` search turns as one: a spot takes its bin's turn")
    place_order: str = S("freedoms", "choice",
        "which searched item of a tier goes next: `freedoms` (the one with fewer freedoms left, then the rank) or `room` (the one with the fewest legal spots left, counted from its declaration, then the rank)")
    place_room_pitch: float = S(1.0, "mm",
        "the pitch `place.order = \"room\"` counts an item's legal spots at: a line's length over it, a region's area over its square")
    place_room_ratio: float = S(2.0, "factor",
        "`place.order = \"room\"`: items whose spot counts differ by less than this factor count as level and go by rank")
    place_lookahead: bool = S(True, "bool",
        "a `Pm.Emits` / `Pm.Limit` part is placed where its still-unplaced partner keeps a legal spot at the limit distance")
    place_lookahead_step: float = S(1.0, "mm",
        "the grid the partner's legal spots are found on for that (its own step if coarser)")
    place_coarse_stride: int = S(4, "count",
        "how many steps apart a scored scan's first pass walks")
    place_coarse_min_radius_steps: float = S(12.0, "steps",
        "a scored scan does a coarse pass first when its radius is at least this many steps; below it one fine pass is cheaper")
    place_refine_spots: int = S(3, "count",
        "how many of the best coarse spots get a fine pass: this many by score, and, where the part's riders refuse some spots, this many of those they take")
    place_block_gap_step: float = S(0.05, "mm",
        "how finely a block's tightest gap is searched")
    place_block_gap_reach: float = S(2.0, "mm",
        "how far a satellite may stand off its pin")
    place_copper_room: bool = S(True, "bool",
        "whether placement keeps room for the copper the script declares: a track or via declared between parts is planned "
        "provisionally, and a part standing Beside another moves out of its way. False places as before")
    place_drc_epsilon: bool = S(False, "bool",
        "whether placement judges a copper, hole and hole-to-hole gap as KiCad's DRC does, a gap short of its rule by no more than the "
        "board's DRC epsilon (`BoardGeometry.drc_epsilon`, 0.0005 mm on a fresh board) counting as clear, and takes the net-tie "
        "exclusion's epsilon from the board. False keeps the nanometre it judged with and the fixed 500 nm. Findings and checks "
        "always take the epsilon")
    place_step_budget: int = S(20_000_000, "count",
        "the most candidates one searched item's step may judge, over all its passes, both faces and the carried vias' giving way; "
        "a step that spends it takes the best spot found so far, or leaves the item unplaced and says how much of the search area "
        "it covered. Counted, not timed: the result does not depend on how busy the machine is. A `place(budget=)` replaces it")
    place_arrangements: bool = S(True, "bool",
        "whether a stamped cell's module arrangements (alternative layouts a module run proved) are searched; false lays every cell's default only, and a module run lays out its default only")
    place_arrangement_options_max: int = S(4, "count",
        "the most options one item or unit of a module may have, its default included; a module that declares more is not partly accepted: its run lays out the default only and says so")
    place_arrangements_max: int = S(16, "count",
        "the most arrangements a module may have, the default included: every combination of its items' and units' options, less those `board.exclude` leaves out")
    place_arrangement_note_chars: int = S(4000, "count",
        "the characters one arrangement note text holds before it is split into numbered texts (a note rides on a User.Comments text of the fragment)")
    place_extent_notice_mm: float = S(1.0, "mm",
        "how far a part may stand past the next part on a side of a module that declares no alternatives before `arrangement.extent_fixed` notes it as setting the module's extent")
    place_arrangement_margin: float = S(0.5, "mm",
        "how much better than the module's default a cell's other arrangement must score before a search takes it; within it the default stands and the step says so. It applies at a decided spot too, where a firm cell's arrangements are each scored once. Not asked when the default has no legal spot, of a cell whose `arrangements=` names its choices, or of an explore's draw")
    place_firm_passes: int = S(8, "count",
        "the most passes over the firm items, each placed against the copper the last pass planned (and, where a Beside part was "
        "refused by a firm part placed before it, with the two taken in the other order), the last one the settled run")
    place_copper_room_tolerance: float = S(0.001, "mm",
        "how far a declared track or via may move between two passes and count as settled")
    place_beside_step: float = S(0.01, "mm",
        "the step a part placed Beside is moved out at, when something already placed is in its way, until the collision rule lets it stand, then bisected back to the first spot that stands")
    place_beside_reach: float = S(2.0, "mm",
        "how far past its standoff from the item a part placed Beside may be moved out to clear what is in its way; past it the part stays at the standoff and the collision is reported")
    place_escape_depth: float = S(1.0, "mm",
        "how far each corridor out of a pad runs in the search: it weighs a candidate that crosses, closes or walls off a pad's corridors (`score.escape_*`); the run score measures them at `score.escape_depth`")
    place_escape_min_pads: int = S(1, "count",
        "a part's pads keep escapes when it has at least this many (3 leaves two-pad parts out)")
    place_escape_via_step: float = S(0.05, "mm",
        "the step a `board.escape` lane's via is searched along its lane at, from the row's end, before it is bisected back to the nearest nanometre")
    place_escape_via_reach: float = S(5.0, "mm",
        "how far along its lane, or its axis, a `board.escape` via is searched before it has no legal spot")
    place_courtyard_touch: float = S(0.0, "mm",
        "how far two courtyards may overlap at least; each pair may also overlap by the two parts' margins (how far KiCad's courtyard polygon lies inside the drawn box) less 0.001 mm, which keeps KiCad's courtyards apart - it counts touching as overlapping")
    place_silk_margin: float = S(0.001, "mm",
        "how much further than the board's silk clearance a place placement chooses keeps one part's silk from another's "
        "silk and mask openings. KiCad compares silk at the clearance itself, with no DRC epsilon, on geometry rounded to "
        "the nanometre, so silk placed at exactly the clearance and then turned off the quarter turns (a stamped cell, a "
        "tangent turn) can come out a nanometre short. A place the script decided, and a rider's place in its group, are "
        "judged at the board's own clearance")
    place_courtyard_polygon_share: float = S(0.98, "share",
        "a courtyard whose polygon covers less of the box round it than this (a slice of a disc, an L, a rectangle turned off the axes) is claimed as KiCad draws it, with no margin; one that covers more is claimed as its box")
    place_conflict_reach: float = S(1.0, "mm",
        "how far outside a box a conflict can still reach; a floor under the largest clearance a rule asks")
    place_fit_room: float = S(10.0, "mm",
        "on a fit frame, how far round the decided content a searched item may go")
    place_via_share_distance: float = S(1.0, "mm",
        "how near a via of its net a carried via that meets another net's copper may be to share it instead; 0 never shares")
    place_via_move_distance: float = S(0.5, "mm",
        "how far such a via may move to clear it; 0 never moves")
    place_via_move_step: float = S(0.05, "mm",
        "the grid a via's move, or its leaving its pad, is searched on")
    place_via_leave_distance: float = S(1.0, "mm",
        "how far a via inside its pad, with no spot clear inside it, may leave it, joined by a new tail; 0 never leaves")
    place_via_relay: bool = S(True, "bool",
        "whether a via field a conflict meets is re-laid in its pad, as a whole, before its vias leave the pad or are dropped; false leaves each via to its own steps")
    place_via_route_distance: float = S(0.5, "mm",
        "how far a via that two or more of a cell's tracks end on may move, its tracks rebuilt from their far ends; 0 leaves it as drawn")
    place_via_search_chunk: int = S(64, "count",
        "how many of the nearest offsets a via's move or leave search judges first; each later window is twice the last, and the search ends at the first window that holds a spot; a speed setting, results are the same")
    place_via_clear_cache: int = S(4096, "count",
        "how many placed routed vias' clear moves a scan keeps, each searched once for every candidate that meets it; a speed setting, results are the same")
    place_drops_keep_share: float = S(0.5, "share",
        "the share of a pad's drops (vias of a `plane()` net in it) the pad keeps, rounded up and never fewer than one: what `drops=Drops.MIN` keeps of each field, and what a pad keeps when a carried drop is dropped to clear another net's copper (1 drops none there)")
    place_edge_step: float = S(0.05, "mm",
        "the step a part on a curved board edge is stepped in from the edge at until the keep-in holds it, before it is bisected back")
    place_pocket_step: float = S(0.5, "mm",
        "the least raster a free-rectangle search blocks the board at; an item's own step is used when coarser")
    place_freedom_min_step: float = S(0.2, "mm",
        "the least step a part's one-freedom search (along an edge, round a ring) walks at; an item's own step is used when coarser")
    place_cutout_step: float = S(0.2, "mm",
        "the step a cutout is slid along a free axis at")
    place_cutout_angle_step: float = S(0.5, "degrees",
        "the step a cutout is turned round its centre at")
    place_escape_lane_via_exit: bool = S(False, "bool",
        "whether a via that fits at the end of a pad's own copper (an escape lane or a stub drawn from it) counts as that pad's way out. Off: a pad on a lane needs a track to get on, on the layer the lane is on, and is walled off when only a via would; on: a via spot is enough, as for a pad with no lane, which keeps the via rule either way")
    place_escape_cell: float = S(0.05, "mm",
        "the grid a pad's path out is searched on")
    place_approach_reach: float = S(8.0, "mm",
        "how far along a pad's airwire toward its nearest target the `escape.pinched` check looks for a gap between two other parts' copper that the pad's track does not fit through")
    place_approach_detour: float = S(2.0, "mm",
        "how far to either side of that airwire a track may go round such a gap, on the pad's layer and crossing no other net's airwire, and still count as a way: a pinch with a way round within it is no `escape.pinched` finding")
    place_split_min_group: int = S(2, "count",
        "the least members a group needs to count as one, in a cell's `split` finding")
    copper_chamfer: float = S(1.0, "mm",
        "how far a right angle is cut back into two 45s")
    copper_arc_radius_track_widths: float = S(3.0, "track widths",
        "the radius of a track's arc corners (`bend=Bend.ARC`), as a multiple of the track's width; `radius=` on the call is in mm and takes precedence")
    copper_pair_chamfer: float = S(0.5, "mm",
        "the same, for a differential pair")
    copper_pair_via_offset: float = S(0.4, "mm",
        "how far clear of its partner a pair's lead vias")
    copper_bridge_half_gap: float = S(1.1, "mm",
        "half the gap a bridge leaves round a crossed track")
    copper_finger_bridge_width: float = S(1.0, "mm",
        "the width of a finger's bridge under a track")
    copper_finger_min_piece: float = S(0.05, "mm",
        "a finger's piece between two bridges no longer than this is not drawn")
    copper_plane_inset: float = S(0.4, "mm",
        "how far a plane is inset from the board edge")
    copper_plane_clearance: float = S(0.2, "mm",
        "a zone's pullback from foreign copper")
    copper_plane_min_width: float = S(0.2, "mm",
        "a zone's minimum filled width")
    copper_pour_outline_width: float = S(0.2, "mm",
        "a pour's outline stroke")
    copper_pour_reach_step: float = S(0.05, "mm",
        "the step `reach=Reach.CURRENT` grows a fitted pour by, so the reach is a multiple of it")
    copper_pour_reach_max: float = S(5.0, "mm",
        "the furthest `reach=Reach.CURRENT` grows a fitted pour; where the need is not met by then a finding says so")
    copper_cell_zones_under_planes: str = S("drop", "choice",
        "a stamped cell's zone the board's own plane covers on its net and layer: `drop` merges it into the plane, `keep` keeps it")
    copper_tap_overlap: float = S(0.005, "mm",
        "how far a tap's copper reaches over its pad's edge; copper that only meets the pad along a line may not read as joined")
    copper_microvia_drill: float = S(0.1, "mm",
        "a micro via's drill (`layers=` one layer from an outer face) when the script gives none")
    copper_straight_tolerance: float = S(0.002, "mm",
        "a track leg whose ends differ by less than this on one axis is drawn straight between them; `measure --copper` judges 0/45/90 by it too")
    write_split_groups: str = S("lift", "choice",
        "the generator's nested groups: `lift` each cell's group out of its module sheet's to the top level (the sheet keeps its own parts), `split` also takes out of a group the parts the script places by steps of their own, `keep` writes them as generated; a group left empty is removed")
    write_keepout_drawings: str = S("admitting", "choice",
        "draw a keepout's outline and name (and its height limit) on its Fab layer, or `User.Comments` for one on both faces or on inner layers only: `admitting` (default) those that admit something, `all` every keepout, `none`")
    write_keepout_line_width: float = S(0.1, "mm",
        "a drawn keepout's outline stroke")
    write_keepout_text_height: float = S(0.8, "mm",
        "a drawn keepout's label height")
    label_text_height: float = S(1.0, "mm",
        "silkscreen text height")
    label_thickness: float = S(0.15, "mm",
        "silkscreen stroke width")
    label_gap: float = S(0.0, "mm",
        "a label's gap from what it names; never less than the board's silk clearance")
    label_slide_step: float = S(0.25, "mm",
        "the step a label slides by along its item's side when a firm part is placed beside it")
    geometry_arc_sag: float = S(0.02, "mm",
        "how far a flattened arc may cut the corner off the real one")
    geometry_index_cells: int = S(16, "count",
        "buckets across the longer side of the spatial index")
    geometry_arc_error_nm: int = S(5000, "nm",
        "arc approximation error when reading pad outlines")
    geometry_cap_steps: int = S(8, "count",
        "segments round each half-circle end of a track's polygon, in Python and in native")
    check_ambient_c: float = S(100.0, "deg C",
        "board temperature the junction estimate starts from (`--ambient`)")
    check_keep_out_mm: float = S(2.0, "mm",
        "how far sense copper stays from a switch node (`--keep-out`)")
    check_rise_c: float = S(10.0, "deg C",
        "the rise a current path is sized for (`--rise`)")
    check_neck_end_share: float = S(0.6, "share",
        "the share of `check.rise_c` the copper at a short neck's two ends is taken to have used (Brooks and Adam's simulated trace ends sit at 57.9 C of a 94.7 C peak); the neck is credited as short when its own conduction rise stays inside the rest. 1 turns the credit off")
    check_neck_resistivity: float = S(2.2e-8, "ohm m",
        "copper's resistivity at the working temperature, ohm m (1.68e-8 at 20 C, 4.04e-3 per K, at 100 C)")
    check_neck_conductivity: float = S(384.0, "W/(m K)",
        "copper's thermal conductivity, W/(m K)")
    check_zone_step: float = S(0.05, "mm",
        "the cell a zone fill is rasterised at to measure its width along a load's route; the width reads within one step")
    check_route_tries: int = S(4, "count",
        "how many times the load's route between two carriers is searched, each search after the first avoiding the zone fill crossings the earlier ones measured narrow")
    check_limits: dict = S(None, "table",
        "a bound per check, e.g. `\"hot-loop\" = 20.0` (`--limit`)", factory=dict)
    parts_order_fields: tuple = S(("Lcsc", "LCSC", "Mpn", "MPN"), "list",
        "a footprint field naming an order code (an LCSC number, an MPN); `parts` warns when a placed part (not `dnp`) has none of them present and non-empty")
    drc_real_kinds: tuple = S(DEFAULT_REAL_KINDS, "list",
        "which violations mean the board is not done, whatever their severity: the `real` bucket (every other kind KiCad reports as an error counts there too, except footprint issues and outstanding)")
    drc_outstanding_kinds: tuple = S(DEFAULT_OUTSTANDING_KINDS, "list",
        "which violations are copper not yet joined: `outstanding`")
    drc_footprint_kinds: tuple = S(DEFAULT_FOOTPRINT_KINDS, "list",
        "which violations are defects in the footprints themselves: `footprint issues`")
    drc_refill_zones: bool = S(True, "bool",
        "refill zones for the check")
    explore_spot_slack: float = S(0.25, "fraction",
        "an explored item draws among spots scoring within this fraction of its best")
    explore_swap_chance: float = S(0.2, "probability",
        "the chance two focused items next in the placement order trade turns")
    explore_rank_power: float = S(1.0, "exponent",
        "an explored item's spot at rank r among its candidates is drawn with weight 1 / r to this power: higher keeps it nearer its best")
    explore_congestion_step: float = S(0.05, "fraction",
        "variants are ranked by the run score, with the worst congestion cell counted in steps of this at `score.congestion` each (0 leaves it out)")
    explore_jobs: int = S(0, "count",
        "worker processes for `--explore`; 0 is the CPU count less one")
    explore_stall_variants: int = S(0, "count",
        "end an explore after this many finished variants without an improvement; 0 is off")
    explore_stall_seconds: float = S(0.0, "seconds",
        "end an explore this many seconds after its last improvement; 0 is off")
    explore_stop_hard_clear: bool = S(False, "bool",
        "end an explore when a variant has none of the hard terms (unplaced parts, critical findings) the plain placement had")
    explore_checkpoint_max_variants: int = S(100000, "count",
        "finished variants an explore's checkpoint records; past it a resume tries those again")
    explore_route_top: int = S(0, "count",
        "after an explore, quick-route its best this many variants by run score, each on its own written board, one at a time, and report each one's route closure beside its score; `--accept` then takes the best clean closure, ties going to the better score. 0 routes none. A run only: a preview writes no board (`--route-top`)")
    pins_exit_mm: float = S(0.5, "mm",
        "the pin map study: how far past its part's courtyard a pin's airwire leaves (its exit point) before it may turn")
    pins_follow_series: bool = S(True, "bool",
        "the pin map study scores a net that reaches a pin through a two-pad series part (a termination resistor) on to the series part's far net, as one connection")
    pins_pair_weight: float = S(5.0, "weight",
        "the pin map study: what a crossing counts where either airwire is a differential pair's (any other counts 1)")
    pins_impedance_weight: float = S(3.0, "weight",
        "the pin map study: what a crossing counts where either airwire's net class names a tuning profile, a controlled impedance, and how many times over such a net's airwire length counts (a differential pair's half too)")
    pins_length_weight: float = S(0.25, "weight",
        "the pin map study: weighted crossings per mm of the studied nets' airwire (0.25: the run score's 4 mm a crossing)")
    pins_bend_weight: float = S(0.005, "weight",
        "the pin map study: weighted crossings per degree a studied net turns from its pin's outward normal toward its target")
    pins_group_weight: float = S(4.0, "weight",
        "the pin map study: weighted crossings per mm a soft `Pm.PinGroup`'s neighbouring nets stand apart beyond the part's pin pitch")
    pins_follow_prefixes: tuple = S(("R", "L", "FB"), "list",
        "the pin map study follows a net on through a two-pad series part only when its reference's leading letters, in any case, equal one of these: a resistor, an inductor, a ferrite bead by default; RT1 is not followed for R, nor a two-pin connector")
    pins_rotations: tuple = S((0.0, 90.0, 180.0, 270.0), "degrees",
        "the turns from where a part stands that the pin map study tries besides its present one; add 45, 135, 225 and 315 for the diagonals")
    pins_seeds: int = S(1, "count",
        "local searches of the pin map study per pose, each with its own fixed random stream")
    pins_anneal_moves: int = S(100, "count",
        "moves each local search of the pin map study tries")
    pins_anneal_start: float = S(1.0, "weight",
        "the pin map study's annealing temperature at its first move, in weighted crossings: a move that costs this much is taken about one time in three (0: only moves that gain)")
    pins_anneal_end: float = S(0.02, "weight",
        "the pin map study's annealing temperature at its last move")
    pins_budget_steps: int = S(3000, "steps",
        "the pin map study's search for each studied part, in steps (one step is one move of a local search, tried whether or not it is taken): it stops there with the best map found and says so, so a board gives the same map at any speed")
    pins_joint_combinations: int = S(64, "count",
        "the most pose combinations the pin map study searches for parts it studies together, their present poses first")
    pins_faces: bool = S(False, "bool",
        "the pin map study also turns a part on the other face where its declaration lets it stand there (`face=Face.EITHER`)")
    pins_gain_min: float = S(0.05, "share",
        "the share of the present total a better pin map must save for a `pins.remap` finding")
    pins_reversed_min: int = S(3, "count",
        "the fewest lines next to each other on a part whose airwires land, on the part they join or on the series parts on the way, in the reverse of their order, for a `pins.reversed` finding")
    pins_placed_share_min: float = S(0.8, "share",
        "the share of a studied group's movable nets that must have a placed far end for the pin map study to advise a map; below it the study says it waits on placement")
    pins_explore_top: int = S(3, "count",
        "the best variants of an explore, by run score, the pin map study runs on (0: none)")
    pins_probe_budget_steps: int = S(150000, "steps",
        "the pin map study's search for each part, in steps, when `placemat apply <id> --search` studies a `pins.remap` suggestion again")
    pins_guard_ms: float = S(10000.0, "ms",
        "a safety net on the pin map study's time for each studied part, scaled with its budget for a longer study: past it the study gives no map and says so in a `setup.pins` warning; 0 is off")
    drc_severities: dict = S(None, "table",
        "a table of KiCad rule names to `error`, `warning` or `ignore`, written into the board's .kicad_pro before DRC", factory=dict)
    route_router_dir: str = S("", "path",
        "the KiCadRoutingTools checkout; empty: `$KRT_DIR`, else `~/work/KRT-upstream`")
    route_quick: bool = S(True, "bool",
        "one routing round rather than the router's full run")
    route_max_iterations: int | None = S(None, "count",
        "cap on the router's search per net; unset: the router's own default")
    route_plane_share: float = S(0.9, "share",
        "how much of the board's own outline a pour must cover to be guarded whole from other nets' tracks while routing (the router's default layers come from each layer's declared role, not this)")
    route_turn_cost: int = S(20000, "cost",
        "what the router charges a turn, per 90 degrees (a 45 half of it), against 1000 a straight grid step: the router's own default of 1000 makes a kink nearly free and its routes stair-step; 20000 measured best on a dense four-layer board (fewer than half the turns, 10% less copper, closure no worse); 1000 gives the router's own behaviour")
    route_smoothing: bool = S(True, "bool",
        "the router's own octolinear smoothing, as it defaults; false skips it")
    route_router_args: tuple = S((), "list",
        "more of the router's own flags (`--direction-preference-cost`, `--heuristic-weight`, `--bus`, `--via-cost`, ...), each a string, appended to its route.py passes (the island nets, the class stages, the main pass); one placemat sets itself (`--nets`, `--layers`, `--escalation`, `--keep-input-copper`, `--turn-cost`, `--smoothing`, `--no-smoothing`, `--power-nets`, `--power-nets-widths`, `--max-iterations`, `--max-probe-iterations`, `--json-out`, `--net-clearances`) is refused. Its `--grid-step` also sets the room turned escape lanes leave for the router's grid snap")
    route_pair_router_args: tuple = S((), "list",
        "the same for the pair router (route_diff.py), which takes flags of its own (`--max-turn-angle`, `--min-turning-radius`, ...) and not all of route.py's")
    route_pair_layers: dict = S(None, "table",
        "the copper layers the pair router may route a differential pair on, for that pair only: a key is the pair's two nets `\"P/N\"` (either order) or a net class name, its value a list of layer names (`{\"USB_D_P/USB_D_N\" = [\"In2.Cu\", \"B.Cu\"]}`); a pair's own nets win over its class. Every other pair routes on the route's own layers. The pairs are routed in one call of the pair router per distinct list, the named ones first. A key that names no pair on the board, or a layer the board does not have, is a `setup.pair_layers` finding and the entry is not used", factory=dict)
    route_net_halos: dict = S(None, "table",
        "a net mapped to a halo in mm (`{\"SW\" = 2.0}`): every router pass keeps other nets' new copper that far from the net's copper, and the net's own new copper that far from everything, to keep coupling off a switch node. Each net is given the larger of its net class clearance and its halo in the clearance map placemat hands the router. Before the route, a pad of another net within the halo whose own copper (an escape, a via) ends inside it is a `setup.net_halo` finding: the router cannot leave it. A key that names no net on the board is a `setup.net_halo` finding and the entry is not used", factory=dict)
    route_islands: tuple = S((), "list",
        "nets with pours whose pads the pours do not reach (a pour net's small taps), `\"NET\"` or `\"NET=WIDTH\"` (mm): routed first and alone, joining only the pads and pieces the pours leave apart, at the netclass width or WIDTH; `placemat route --islands` adds to them")
    route_diff_pair_gap: float = S(0.0, "mm",
        "mm between a pair's tracks; 0 is the net class's diff pair gap (the router never goes below the class clearance)")
    route_diff_pair_width: float = S(0.0, "mm",
        "mm, a pair's track width; 0 is the net class's diff pair width")
    route_adopt_tolerance: float = S(0.001, "mm",
        "mm any kept pad may lie from where the parts' common motion puts it before the kept routes joining them are dropped")
    run_max_time_s: float = S(0.0, "seconds",
        "stop a `run` or `preview` after this many seconds of placing, at the next point it can be resumed from (its finished steps are kept and replayed by the rerun); 0 is no cap. `--max-time`. Wall-clock, so it depends on machine load")
    run_step_warn_s: float = S(0.0, "seconds",
        "a step still working after this many seconds sends a live event and gets a finding naming the item, its seconds and the pass it was in; 0 is never. `--step-warn`")
    run_step_limit_s: float = S(0.0, "seconds",
        "a step still working after this many seconds gives up: it is left unplaced, or at the best legal spot its scan had found, with a finding, and the resolve goes on with the next item; checked between a scan's passes; 0 is never. `--step-limit`. Wall-clock, so which steps give up depends on machine load, unlike a candidate budget; such a step is searched again by the next run")
    run_parallel: bool = S(True, "bool",
        "`run` starts kicad-cli's DRC and renders as soon as the board is written and runs the design checks while they work, so those stages take the time of the longest rather than the sum (a measured core board's run, 109 s -> 83 s on a loaded machine); the renders use several cores meanwhile. false runs them one after another. The run's record is the same either way, but for the stages' times")
    timeout_generate: int = S(900, "seconds",
        "seconds for `pcb layout`")
    timeout_drc: int = S(600, "seconds",
        "seconds for kicad-cli DRC")
    timeout_route: int = S(3600, "seconds",
        "seconds for the router")
    timeout_render: int = S(300, "seconds",
        "seconds for a render")
    noise_patterns: tuple = S((), "list",
        "extra KiCad stderr patterns to suppress, ADDED to the built-ins")
    best_airwire_noise: float = S(0.01, "fraction",
        "how far airwire may move, as a fraction, before a run counts as better or worse than its family's best: kicad-cli picks different ratsnest edges each run for a byte-identical board")
    best_crossing_noise: float = S(0.02, "fraction",
        "how far the crossings' term may move, as a fraction, before a score counts as better or worse: kicad-cli's ratsnest varies run to run")
    score_unplaced: float = S(2000.0, "mm",
        "mm a part left unplaced costs the run score, times its priority's multiplier")
    score_unplaced_high: float = S(2.0, "multiplier",
        "the unplaced multiplier for a part declared `priority=HIGH`")
    score_unplaced_default: float = S(1.0, "multiplier",
        "the unplaced multiplier for a part with no declared priority")
    score_unplaced_low: float = S(0.5, "multiplier",
        "the unplaced multiplier for a part declared `priority=LOW`")
    score_drc: float = S(200.0, "mm",
        "mm a real DRC violation costs")
    score_link_over: float = S(20.0, "mm",
        "mm per millimetre a link is past its limit, times the link's weight")
    score_fixed: float = S(200.0, "mm",
        "mm a decided item (fixed, a cutout, a keepout) not legal where it was put costs")
    score_copper: float = S(200.0, "mm",
        "mm planned copper that meets another net, crosses a keepout or cannot bridge costs")
    score_label: float = S(50.0, "mm",
        "mm a label with a part on it costs")
    score_setup: float = S(0.0, "mm",
        "mm a setup finding costs: the same every run of a script (an undeclared part, a layer the board lacks)")
    score_crossing: float = S(4.0, "mm",
        "mm a ratsnest crossing costs, in the run score and in the search")
    score_crossing_plane: float = S(0.0, "share",
        "a crossing with a plane's or free net's airwire, as a share of `score.crossing`: each of its pads drops to the plane by a via")
    score_pair_crossing: float = S(100.0, "mm",
        "mm a differential pair (a net class's own, board_pairs) crossing itself costs, in place of `score.crossing`: such a pair has to exchange sides to route coupled, so a swap of two identical parts or a turned part is worth wire")
    score_escape_crossed: float = S(20.0, "mm",
        "mm two escapes from one part's pins crossing near its pin row cost")
    score_escape_depth: float = S(1.5, "mm",
        "the corridor length the escape findings, and so the run score, are measured at, whatever `place.escape_depth` the search used, so runs at different search depths compare")
    score_escape_closed: float = S(50.0, "mm",
        "mm a pad whose last route toward what it connects to is closed costs")
    score_escape_walled: float = S(400.0, "mm",
        "mm a pad with no route out at all costs. A pad that copper of its own net already leaves with a way on (a track that reaches another pad of the net, a via in it, a pour over it) is not counted, closed or walled; a track or an escape's lane that ends in the air is the pad's way out only as far as it goes, and the pad is walled when no track or via gets on from where the copper ends. What walls a pad (pads on a layer the pad shares, a through-hole pad on every layer it spans, unplated holes, copper, and where a via is wanted the rule areas that forbid vias) is named by owner, \"track NET\", \"via NET\", \"pour NET\" or \"the escape lane of U1 pin 53\". A pad whose net has no other pad on the board (a pin the cell hands off to the board above it; not a no-connect net: `NC_...`, `unconnected-(...)`, or a net named under an instance, with a dot) is reported at the end of the run when no track or via gets out of it, from the end of its own net's copper on it (a stub, an escape's lane) where it has any: \"no other pad is on the net, so it leaves the board here, and it is walled off by ...\". Such a pin keeps no corridor in the placement search; `board.escape` names the pins whose routes out are to be kept")
    score_escape_lane: float = S(400.0, "mm",
        "mm a declared `board.escape` lane costs that another net's pad, hole or copper already placed blocks, or whose via has no legal spot: in the search at each candidate, and in the run score as the `escape_lane` finding")
    score_congestion: float = S(10.0, "mm",
        "explore: mm per `explore.congestion_step` of the worst RUDY cell")
    score_via_share: float = S(1.0, "mm",
        "mm the search adds to a spot for each carried via that shares a via of its net there")
    score_via_move: float = S(2.0, "mm",
        "mm for each carried via that moves there")
    score_via_drop: float = S(10.0, "mm",
        "mm for each plane drop dropped there")
    score_back_face: float = S(2.0, "mm",
        "mm the search adds to a spot on the back face of an item placed with `face=Face.EITHER`, so an equal spot is the front's; no item with a fixed face pays it")
    score_arrangement: float = S(0.0, "mm",
        "mm the search adds to a cell's non-default arrangement, so an equal score keeps the module's own layout; a project raises it to prefer the module's default by that much")
    score_push: float = S(10.0, "mm",
        "mm-equivalent: `score.push` times a push's modelled value over its limit, at the search")
    score_via_leave: float = S(4.0, "mm",
        "mm for each carried via that leaves its pad there, between move and shorten")
    score_via_relay: float = S(3.0, "mm",
        "mm for each via field re-laid there, once, between move and leave")
    score_via_relay_moved: float = S(0.5, "mm",
        "mm for each via a relay moves or adds")
    score_via_relay_gap: float = S(1.0, "mm",
        "mm for each empty site a relay leaves in the field's grid, beyond the drawn field's")
    score_via_relay_pitch: float = S(4.0, "mm",
        "mm for each mm the field's line spacings, summed, depart from the pitch it was drawn at")
    score_via_route: float = S(3.0, "mm",
        "mm for each routed via that moves with its tracks rebuilt there, between move and leave")
    score_via_shorten: float = S(5.0, "mm",
        "mm for each carried plane drop shortened to the plane's nearest layer instead of dropped, between move and drop")
    solve_enabled: bool = S(False, "bool",
        "give the searched tier its hints from a global solve of the whole netlist, before any item is scanned")
    solve_iterations: int = S(200, "count",
        "the solve's conjugate-gradient cap per axis per round")
    solve_tolerance: float = S(1e-6, "residual",
        "the residual the solve stops at")
    solve_rounds: int = S(8, "count",
        "solve-then-spread rounds, the pull toward the spread rising by `solve.spread_growth` each round")
    solve_centre_pull: float = S(0.01, "weight",
        "the weak pull of every part toward the middle of the board, per unit spring")
    solve_spread_pull: float = S(0.01, "weight",
        "the first round's pull of each part toward its spread cell")
    solve_spread_growth: float = S(2.0, "factor",
        "the pull's growth each round after: round n pulls with `spread_pull * growth ** n`")
    preview_converter: str = S("rsvg-convert --width {width} -o {png} {svg}", "command",
        "the command `placemat preview` runs to turn its SVG into a PNG; `{svg}`, `{png}` and `{width}` are filled in")
    preview_px_per_mm: float = S(40.0, "px/mm",
        "the preview PNG's resolution, pixels per millimetre of the drawing")
    preview_model_edge_px: int = S(1568, "pixels",
        "the long edge, in pixels, an image is scaled to before the model reading it sees it - an assumption about that model, which placemat cannot know; the preview reports the resolution the model would then see. 0 reports nothing")
    cleanup_enabled: bool = S(True, "bool",
        "after the searched tier, move and swap plain searched parts where that shortens their wire and declared links")
    cleanup_passes: int = S(2, "count",
        "passes over the movable parts; one that changes nothing ends it")
    cleanup_search_radius: float = S(3.0, "mm",
        "how far round its optimal region, and round where it stands, a part is searched")
    cleanup_search_step: float = S(0.5, "mm",
        "that search's step")
    cleanup_swap_neighbours: int = S(4, "count",
        "each part is offered a swap with this many of its nearest movable neighbours: both lifted, each searched round the other's old spot")
    cleanup_swap_radius: float = S(1.0, "mm",
        "how far round the other's old spot each part of a swap is searched")

    studio_port: int = S(0, "port",
        "the port `placemat studio` listens on, on 127.0.0.1 only; 0 is any free one. Not part of a run's id")
    studio_debounce_ms: int = S(300, "ms",
        "a change to a watched file starts a resolve after this long without another")
    studio_open: bool = S(True, "bool",
        "open the browser on the page; `--no-open` overrides")
    studio_keep: int = S(10, "count",
        "resolves kept, so the page can compare any two")
    studio_poll_ms: int = S(200, "ms",
        "how often the watched files' modification times are read")
    studio_explore_fps: float = S(2.0, "per second",
        "how many times a second the board is redrawn for a live explore, to the best variant so far (above 0)")
    studio_follow_hold_s: float = S(10.0, "seconds",
        "while the studio follows the latest command, a newer one that starts is not shown for this long after the viewer selected an item, opened a finding or zoomed; the page offers it instead (0 shows it at once)")
    studio_note_age_s: int = S(3600, "seconds",
        "a note left in the studio is hidden after this long; 0 keeps it")
    studio_notes_keep: int = S(100, "count",
        "notes kept in a board's notes file")
    studio_cancel_grace_ms: int = S(2000, "ms",
        "a resolve asked to stop that has not stopped by then has its worker restarted")
    studio_suggestions_per_lever: int = S(3, "count",
        "a finding's suggestions for one lever (which side to place beside): the best this many")
    studio_try_timeout_s: int = S(60, "seconds",
        "a try of a suggestion (a resolve of the edited script) is stopped after this long")
    studio_probe_budget_s: int = S(120, "seconds",
        "a probe of a searched suggestion stops after this long in all, keeping the best candidate so far")
    studio_probe_candidates: int = S(12, "count",
        "the most candidates (resolves of the edited script) a probe tries, the first and the last check included")
    studio_apply: bool = S(True, "bool",
        "false: the studio shows suggestions and diffs but refuses to write them")
    studio_3d_kicad_cli: str = S("", "path",
        "the kicad-cli the 3D view converts models with; empty finds it on the PATH")
    studio_3d_model_dirs: str = S("", "path",
        "more folders KiCad's own 3D model library may be in, separated by the platform's path separator, tried after the standard install places")
    studio_3d_cache_dir: str = S("", "path",
        "where converted 3D models are kept, shared by every project; empty is placemat/models in the user's cache folder")
    studio_3d_cache_mb: int = S(512, "count",
        "megabytes the model cache may hold; over it the least recently used meshes are removed")
    studio_3d_batch: int = S(8, "count",
        "models converted per kicad-cli run (the progress granularity: each run costs about 0.3 s more than its export)")
    studio_3d_batch_timeout_s: int = S(120, "seconds",
        "a kicad-cli model conversion batch is stopped after this long, and its models are tried one by one")
    studio_3d_model_tris: int = S(30000, "count",
        "a model mesh over this many triangles is simplified (vertex clustering) once, when it is converted")
    studio_3d_max_tris: int = S(4000000, "count",
        "triangles the 3D view draws at most; past it the parts are drawn as plates and the view says so")
    studio_3d_appear_ms: int = S(200, "ms",
        "a part arriving in the 3D view drops in and fades over this long; 0 shows it at once")
    studio_3d_plate_mm: float = S(0.1, "mm",
        "how far the plate of a part with no 3D model stands off its face")
    studio_3d_spread_mm: float = S(4.0, "mm",
        "the 3D view's Spread: how much further apart each copper layer stands from the next when the stack is pulled apart")
    studio_3d_spread_ms: int = S(450, "ms",
        "the 3D view's Spread: how long the layers take to part and close; 0 moves them at once")
    studio_builder_grid_mm: float = S(0.5, "mm",
        "the board builder: a dragged outline dimension or vertex snaps to this step, and a suggested size is rounded up to it")
    studio_builder_max_fill: float = S(0.5, "share",
        "the board builder: the most of one face the parts' courtyards may fill in a suggested board size (above 0, at most 1); the outline dialog's fill field overrides it for one board. The one measured board is filled 0.33 per face on average")
    studio_builder_aspect: float = S(1.0, "ratio",
        "the board builder: the width over the height a suggested rectangle takes before the user changes it")

    facts_confirmed: str = S("", "text",
        "the old single digest, read for any script with no entry in `facts.boards`; replaced by that table on the next `--confirm`")
    facts_boards: dict = S(None, "table",
        "`[facts.boards]`: a script's path relative to this placemat.toml -> the digest of its last `placemat facts --confirm`; placemat's own record, not part of a run's id", factory=dict)

    # Where each value came from: a file path, "flag", or "default". Never
    # part of equality or of the run id: it says where, not what.
    sources: dict = field(default_factory=dict, compare=False)

    @staticmethod
    def keys() -> tuple:
        return tuple(f.name for f in fields(Settings) if f.name != "sources")

    def source_of(self, name: str) -> str:
        return self.sources.get(name, "default")

    def json(self) -> str:
        """Canonical, for the run id: the values only, sorted, stable across
        dict ordering. facts_confirmed and facts_boards are left out: it is placemat's own
        record of a user's confirmation, not a fact that changes a run, so
        confirming never gives a script a new run id. The studio's settings are
        left out too: they say how a view is served, not what is placed; so are `[run]`'s, which say how long a command may take."""
        out = {}
        for name in self.keys():
            if name in ("facts_confirmed", "facts_boards") or name.startswith(("studio_", "run_")):
                continue
            v = getattr(self, name)
            out[name] = sorted(v.items()) if isinstance(v, dict) else (
                list(v) if isinstance(v, tuple) else v)
        return json.dumps(out, sort_keys=True, separators=(",", ":"))

    def with_sources(self, sources: dict) -> "Settings":
        return replace(self, sources=dict(sources))


# `[check.limits]`, `[drc.severities]`, `[facts.boards]`, `[route.pair_layers]` and `[route.net_halos]` are the sub-tables: each section is two words.
_SUBTABLES = ("check.limits", "drc.severities", "facts.boards", "route.pair_layers", "route.net_halos")


def split_key(name: str) -> tuple:
    """`place_step` -> ("place", "step"). The section is the first word."""
    section, _, key = name.partition("_")
    return section, key


def join_key(section: str, key: str) -> str:
    """("place", "step") -> `place_step`; ("check.limits", "") -> `check_limits`."""
    if section in _SUBTABLES:
        return section.replace(".", "_")
    return "%s_%s" % (section, key)


_active: Settings | None = None


def active() -> Settings:
    """The settings bound for this run, or the defaults when nothing is."""
    return _active if _active is not None else Settings()


@contextmanager
def bind(real: Settings):
    global _active
    previous = _active
    _active = real
    try:
        yield real
    finally:
        _active = previous


def _files(start) -> list:
    """Every placemat.toml from the start directory up to the filesystem
    root, FARTHEST FIRST so the nearest one is applied last and wins."""
    d = Path(start).resolve()
    if d.is_file():
        d = d.parent
    found = [p / FILENAME for p in (d, *d.parents) if (p / FILENAME).is_file()]
    return list(reversed(found))


def parse_islands(items) -> dict:
    """`[route] islands` / `--islands` entries, "NET" or "NET=WIDTH" (mm,
    above 0), as {net: width or None}."""
    out = {}
    for item in items or ():
        net, eq, width = str(item).partition("=")
        try:
            w = float(width) if eq else None
        except ValueError:
            w = 0.0
        if not net or (eq and not (w or 0) > 0):
            raise ValueError("%r is not NET or NET=WIDTH (a width in mm, above 0)" % item)
        out[net] = w
    return out


def router_flag(args, name: str):
    """The value of the router flag `name` in `args` (`--flag value` or `--flag=value`) as a number, or None."""
    args = list(args)
    for i, a in enumerate(args):
        flag, eq, value = a.partition("=")
        if flag == name:
            try:
                return float(value if eq else args[i + 1])
            except (IndexError, ValueError):
                return None
    return None


# The router flags placemat sets on every pass: [route] router_args may not name them.
_ROUTER_OWNED = frozenset(("--nets", "--layers", "--escalation", "--keep-input-copper", "--turn-cost", "--smoothing",
                           "--no-smoothing", "--power-nets", "--power-nets-widths", "--max-iterations",
                           "--max-probe-iterations", "--json-out", "--net-clearances"))


# A copper layer's name as KiCad spells it: F.Cu, In1.Cu to In30.Cu, B.Cu.
_COPPER_LAYER = re.compile(r"^(F|B|In([1-9]|[12][0-9]|30))\.Cu$")


class SettingsError(ValueError):
    """A placemat.toml that cannot be obeyed. A setting that quietly does
    nothing reads as though it is in force, so this is never a warning."""


# Keys with a fixed set of values.
_CHOICES = {"place_envelope": ("courtyard", "physical", "union"), "place_rotations": ("all", "declared"), "place_order": ("freedoms", "room"),
            "copper_cell_zones_under_planes": ("drop", "keep"), "write_split_groups": ("lift", "split", "keep"),
            "write_keepout_drawings": ("admitting", "all", "none")}

# Keys with a floor. A value at or below it is a setting that cannot work: a
# zero scan step never moves, a zero timeout never runs. Weights are absent
# from this table because weighting a dimension at nothing is a real choice.
_ABOVE_ZERO = frozenset((
    "place_radius", "place_step", "place_bearing_step", "place_tangent_bin", "place_lookahead_step", "place_room_pitch", "place_coarse_min_radius_steps", "place_coarse_stride",
    "place_refine_spots", "place_step_budget", "place_arrangement_options_max", "place_arrangements_max", "place_arrangement_note_chars", "place_block_gap_step", "place_block_gap_reach", "place_beside_step", "place_beside_reach", "place_firm_passes", "place_copper_room_tolerance", "place_escape_depth", "place_escape_via_step", "place_escape_via_reach", "place_edge_step", "place_pocket_step", "place_freedom_min_step", "place_cutout_step", "place_cutout_angle_step", "place_escape_cell", "place_approach_reach", "place_approach_detour", "geometry_cap_steps", "solve_spread_growth", "solve_centre_pull", "score_escape_depth", "place_via_move_step", "place_via_search_chunk", "place_via_clear_cache",
    "place_conflict_reach", "place_fit_room", "copper_arc_radius_track_widths", "copper_bridge_half_gap", "copper_finger_bridge_width", "copper_finger_min_piece",
    "copper_plane_min_width", "copper_pour_outline_width", "copper_pour_reach_step", "copper_pour_reach_max", "copper_microvia_drill", "label_text_height",
    "label_thickness", "label_slide_step", "geometry_arc_sag", "geometry_index_cells",
    "geometry_arc_error_nm", "check_rise_c", "check_zone_step", "check_route_tries", "check_neck_resistivity", "check_neck_conductivity",
    "studio_3d_cache_mb", "studio_3d_batch", "studio_3d_batch_timeout_s", "studio_3d_model_tris", "studio_3d_max_tris", "studio_3d_plate_mm", "studio_3d_spread_mm",     "studio_keep", "studio_notes_keep", "studio_poll_ms", "studio_explore_fps", "studio_suggestions_per_lever", "studio_try_timeout_s", "studio_probe_budget_s", "studio_probe_candidates", "studio_builder_grid_mm", "studio_builder_max_fill", "studio_builder_aspect", "timeout_generate", "timeout_drc", "timeout_route", "timeout_render",
    "solve_iterations", "solve_tolerance", "solve_rounds", "cleanup_search_radius", "cleanup_search_step", "cleanup_swap_radius", "preview_px_per_mm",
    "route_plane_share", "route_adopt_tolerance", "place_courtyard_polygon_share", "write_keepout_line_width", "write_keepout_text_height",
    "pins_seeds", "pins_anneal_moves", "pins_budget_steps", "pins_reversed_min", "pins_joint_combinations", "pins_probe_budget_steps"))
_AT_LEAST_ZERO = frozenset((
    "studio_follow_hold_s", "rank_area_weight", "rank_pins_weight", "place_drops_keep_share", "route_turn_cost", "place_courtyard_touch", "place_silk_margin", "cleanup_passes", "cleanup_swap_neighbours", "preview_model_edge_px", "studio_3d_appear_ms", "studio_3d_spread_ms", "studio_note_age_s", "studio_port", "studio_debounce_ms", "studio_cancel_grace_ms", "copper_chamfer", "best_airwire_noise",
    "run_max_time_s", "run_step_warn_s", "run_step_limit_s", "best_crossing_noise", "score_unplaced", "score_unplaced_high", "score_unplaced_default", "score_unplaced_low",
    "score_drc", "score_link_over", "score_fixed", "score_copper", "score_label", "score_setup", "score_crossing",
    "score_crossing_plane", "score_escape_crossed", "score_escape_closed", "score_escape_walled", "score_escape_lane", "score_congestion",
    "copper_pair_chamfer", "copper_pair_via_offset", "copper_plane_inset", "copper_straight_tolerance",
    "copper_plane_clearance", "label_gap", "check_keep_out_mm", "route_diff_pair_gap", "route_diff_pair_width",
    "score_pair_crossing", "copper_tap_overlap", "solve_spread_pull", "place_via_share_distance", "place_via_move_distance", "place_via_leave_distance", "place_via_route_distance", "score_via_route", "score_via_share", "score_via_leave",
    "score_via_move", "score_via_drop", "score_via_shorten", "score_push", "score_back_face", "score_arrangement", "place_extent_notice_mm", "place_arrangement_margin",
    "score_via_relay", "score_via_relay_moved", "score_via_relay_gap", "score_via_relay_pitch",
    "pins_exit_mm", "pins_pair_weight", "pins_impedance_weight", "pins_length_weight", "pins_bend_weight", "pins_group_weight", "pins_anneal_start",
    "pins_anneal_end", "pins_gain_min", "pins_placed_share_min", "pins_explore_top", "pins_guard_ms", "explore_route_top"))
# A floor of 2: below it a "group" can never be more than one part, which
# is not a group at all.
_AT_LEAST_TWO = frozenset(("place_split_min_group", "place_room_ratio"))
_UNIT_INTERVAL = frozenset(("check_neck_end_share", "studio_builder_max_fill"))      # a share: 0 to 1


def _declared(name: str) -> str:
    """A field's declared type, as text: `from __future__ import annotations`
    means every annotation is already a string."""
    return str({f.name: f.type for f in fields(Settings)}[name])


def _nearest(dotted: str) -> str:
    """The valid key closest to a mistyped one, for the error message."""
    import difflib
    known = ["%s.%s" % split_key(k) for k in Settings.keys()]
    close = difflib.get_close_matches(dotted, known, n=1, cutoff=0.5)
    return close[0] if close else ""


def _validate(name: str, value, path: str):
    """One setting, against the type it is declared as and the floor it has.
    Raises rather than warns: a rejected setting can be fixed, an ignored one
    reads as though it were in force."""
    dotted = "%s.%s" % split_key(name)
    text = _declared(name)
    said = lambda want: SettingsError("%s: %s must be %s, not %r" % (path, dotted, want, value))
    if "bool" in text:
        if not isinstance(value, bool):
            raise said("true or false")
    elif isinstance(value, bool):
        raise said("a number" if ("float" in text or "int" in text) else "not true or false")
    elif "float" in text:
        if not isinstance(value, (int, float)):
            raise said("a number")
    elif "int" in text:
        if not isinstance(value, int):
            raise said("a whole number")
    elif "tuple" in text:
        if not isinstance(value, (list, tuple)):
            raise said("a list")
    elif "dict" in text:
        if not isinstance(value, dict):
            raise said("a table")
    elif "str" in text:
        if not isinstance(value, str):
            raise said("a string")
    if name == "pins_rotations":
        bad = [v for v in value if isinstance(v, bool) or not isinstance(v, (int, float))]
        if bad:
            raise SettingsError("%s: pins.rotations: every entry is a turn in degrees, not %r" % (path, bad[0]))
        bad = [v for v in value if not math.isfinite(v)]
        if bad or not value:
            raise SettingsError("%s: pins.rotations: a list of at least one finite turn in degrees, not %r" % (path, list(value)))
    if name == "pins_follow_prefixes":
        if not all(isinstance(v, str) and v for v in value):
            raise SettingsError("%s: pins.follow_prefixes: every entry is a reference prefix, a string of letters, not %r" % (path, list(value)))
    if name == "drc_severities":
        bad = {k: v for k, v in value.items() if v not in ("error", "warning", "ignore")}
        if bad:
            k, v = sorted(bad.items())[0]
            raise SettingsError("%s: drc.severities.%s must be error, warning or ignore, not %r" % (path, k, v))
    if name in ("route_router_args", "route_pair_router_args"):
        if not all(isinstance(v, str) for v in value):
            raise SettingsError("%s: %s: every entry is a string (a command-line word), not %r" % (
                path, dotted, next(v for v in value if not isinstance(v, str))))
        owned = sorted({v.split("=", 1)[0] for v in value if v.startswith("-")
                        and any(o.startswith(v.split("=", 1)[0]) and len(v.split("=", 1)[0]) > 2 for o in _ROUTER_OWNED)})
        if owned:
            raise SettingsError("%s: %s: %s is set by placemat itself (%s)" % (
                path, dotted, ", ".join(owned), "[route] turn_cost, smoothing, islands, net_halos and route --iterations name them"))
    if name == "route_pair_layers":
        for key, layers in value.items():
            if not (isinstance(layers, (list, tuple)) and layers and all(isinstance(l, str) for l in layers)):
                raise SettingsError("%s: route.pair_layers.%s must be a list of layer names, not %r" % (path, json.dumps(key), layers))
            bad = [l for l in layers if not _COPPER_LAYER.match(l)]
            if bad:
                raise SettingsError("%s: route.pair_layers.%s: %s is not a copper layer (F.Cu, In1.Cu to In30.Cu, B.Cu)" % (
                    path, json.dumps(key), ", ".join(bad)))
    if name == "route_net_halos":
        for key, halo in value.items():
            if isinstance(halo, bool) or not isinstance(halo, (int, float)) or not halo > 0:
                raise SettingsError("%s: route.net_halos.%s must be a halo in mm, above 0, not %r" % (path, json.dumps(key), halo))
    if name == "route_islands":
        try:
            parse_islands(value)
        except ValueError as e:
            raise SettingsError("%s: %s: %s" % (path, dotted, e)) from None
    if name in _CHOICES and value not in _CHOICES[name]:
        raise SettingsError("%s: %s must be %s, not %r" % (
            path, dotted, ", ".join(_CHOICES[name][:-1]) + " or " + _CHOICES[name][-1], value))
    if name in _ABOVE_ZERO and not value > 0:
        raise SettingsError("%s: %s must be greater than 0, not %r" % (path, dotted, value))
    if name in _AT_LEAST_ZERO and value < 0:
        raise SettingsError("%s: %s may not be negative, not %r" % (path, dotted, value))
    if name in _UNIT_INTERVAL and not 0 <= value <= 1:
        raise SettingsError("%s: %s must be between 0 and 1, not %r" % (path, dotted, value))
    if name in _AT_LEAST_TWO and value < 2:
        raise SettingsError("%s: %s must be at least 2, not %r" % (path, dotted, value))


# Keys retired because they named a board fact: placemat.toml holds no
# board fact, and a project that still sets one is told where it moved.
_RETIRED = {
    "check_copper_oz": "the board's own copper weight, read per layer from its stackup",
    "route_layers": "each layer's role in the board's stackup (signal/mixed routes, F.Cu and B.Cu always)",
    "route_diff_pairs": "a net class's diff_pair_width/diff_pair_gap in the board's .zen",
}

# Keys retired because what they set is now counted another way: {key: what replaced it}. A time is not a count of
# steps, so the old value is not carried over; the project is told what to set instead.
_REPLACED = {
    "pins_budget_ms": "pins.budget_steps, a count of the study's steps, so a board gives the same map at any speed",
    "pins_probe_budget_ms": "pins.probe_budget_steps, a count of the study's steps, so a board gives the same map at any speed",
}


def _replaced(where, name: str) -> SettingsError:
    return SettingsError("%s: %s.%s is retired; set %s" % ((where,) + split_key(name) + (_REPLACED[name],)))


def _flatten(data: dict, path) -> dict:
    """A parsed TOML document as {attribute name: value}. Sub-tables named in
    _SUBTABLES are one value; any other nested table is a section."""
    out = {}
    known = set(Settings.keys())
    sections = sorted({split_key(k)[0] for k in known})
    for section, body in data.items():
        if not isinstance(body, dict):
            raise SettingsError("%s: %r is a bare value; every setting lives in a "
                                "section, e.g. [place]\n%s = ..." % (path, section, section))
        if section not in sections:
            raise SettingsError("%s: [%s] is not a section placemat knows; it has %s"
                                % (path, section, ", ".join(sections)))
        for key, value in body.items():
            full = "%s.%s" % (section, key)
            if isinstance(value, dict):
                if full not in _SUBTABLES:
                    raise SettingsError("%s: [%s] is not a section placemat knows" % (path, full))
                out[join_key(full, "")] = dict(value)
                continue
            name = join_key(section, key)
            if name in _REPLACED:
                raise _replaced(path, name)
            if name in _RETIRED:
                raise SettingsError("%s: %s is retired; it named a board fact, now read from %s"
                                    % (path, full, _RETIRED[name]))
            if name not in known:
                hint = _nearest(full)
                raise SettingsError("%s: %s is not a setting placemat has%s"
                                    % (path, full, (", did you mean %s?" % hint) if hint else ""))
            out[name] = value
    return out


def _coerce(name: str, value):
    """A TOML list becomes the tuple the field is declared as."""
    declared = {f.name: f.type for f in fields(Settings)}.get(name)
    if declared is not None and "tuple" in str(declared) and isinstance(value, list):
        return tuple(value)
    return value


def _script_tables(data: dict, path) -> dict:
    """The `[scripts."<path>".<section>]` tables of a parsed document, as
    {script path: {attribute name: value}}, each body validated like the base
    sections. A path is relative to the folder of the file holding it and must
    name a file there: a stale or mistyped one would quietly do nothing."""
    tables = data.get("scripts", {})
    if not isinstance(tables, dict):
        raise SettingsError("%s: [scripts] holds one table per script path, e.g. "
                            "[scripts.\"modules/m/M_layout.py\".solve]" % path)
    out = {}
    for key, body in tables.items():
        label = "%s [scripts.%s]" % (path, json.dumps(key))
        if not isinstance(body, dict):
            raise SettingsError("%s must be a table of sections, e.g. [scripts.%s.solve]" % (label, json.dumps(key)))
        if not (Path(path).parent / key).is_file():
            raise SettingsError("%s: no script %s beside %s" % (label, key, path))
        if "facts" in body:
            raise SettingsError("%s: [facts] is placemat's own record and is not set per script" % label)
        flat = _flatten(body, label)
        for name, value in flat.items():
            _validate(name, value, label)
        out[key] = flat
    return out


def load(start, overrides=None, script=None) -> Settings:
    """The settings for a board: built-in defaults, then every placemat.toml
    from the filesystem root down to the board's own directory (so the nearest
    wins per key), then, for `script`, the `[scripts."<path>"]` tables of those
    files that name it, then the CLI overrides."""
    values, sources, per_script = {}, {}, []
    for path in _files(start):
        try:
            from . import context
            held = context.overlay_text(path)          # a try of a suggestion reads the edited text, nothing on disk
            data = tomllib.loads(held if held is not None else path.read_text())
        except tomllib.TOMLDecodeError as e:
            raise SettingsError("%s is not valid TOML: %s" % (path, e))
        tables = _script_tables(data, path)
        data = {k: v for k, v in data.items() if k != "scripts"}
        per_script.append((path, tables))
        for name, value in _flatten(data, path).items():
            _validate(name, value, str(path))
            values[name] = value
            sources[name] = str(path)
    if script is not None:
        script = Path(script).resolve()
        for path, tables in per_script:
            try:
                key = script.relative_to(path.parent.resolve()).as_posix()
            except ValueError:
                continue
            for name, value in tables.get(key, {}).items():
                values[name] = value
                sources[name] = "%s [scripts.%s]" % (path, json.dumps(key))
    for name, value in (overrides or {}).items():
        if name in _REPLACED:
            raise _replaced("flag", name)
        if name not in set(Settings.keys()):
            raise SettingsError("%s is not a setting placemat has" % name)
        _validate(name, value, "flag")
        values[name] = value
        sources[name] = "flag"
    coerced = {name: _coerce(name, value) for name, value in values.items()}
    start, end = (coerced.get(n, _default_of(next(f for f in fields(Settings) if f.name == n)))
                  for n in ("pins_anneal_start", "pins_anneal_end"))
    if end > start:
        raise SettingsError("pins.anneal_end (%r) is above pins.anneal_start (%r)" % (end, start))
    return Settings(**coerced).with_sources(sources)


# ------------------------------------------------------------ settings as documentation
_SUBTABLES_BY_NAME = frozenset(s.replace(".", "_") for s in _SUBTABLES)


def meta(name: str) -> dict:
    """{"unit", "doc"} of a setting."""
    return {f.name: f.metadata for f in fields(Settings)}[name]


def describe(name: str) -> str:
    """A setting's meaning, with the values it may have when it is a choice."""
    text = meta(name)["doc"].strip()
    choices = _CHOICES.get(name)
    if choices:
        text += ("" if text.endswith((".", ")", ":")) else ".") + " One of: %s." % ", ".join(choices)
    return text


def _default_of(f):
    return f.default_factory() if f.default is MISSING else f.default


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{}" if not v else "{ " + ", ".join("%s = %s" % (json.dumps(k), _toml_value(x)) for k, x in v.items()) + " }"
    return repr(v)


def _shown_default(v) -> str:
    if v is None:
        return "unset"
    return _toml_value(v)


def docs_table() -> str:
    """The api.md settings table, from the fields: key, default, unit, meaning."""
    rows = ["| key | default | unit | what it governs |", "|---|---|---|---|"]
    for f in fields(Settings):
        if f.name == "sources":
            continue
        section, key = split_key(f.name)
        name = "%s.%s" % (section, key)
        rows.append("| `%s` | %s | %s | %s |" % (name, "`%s`" % _shown_default(_default_of(f)).replace("|", "\\|"),
                                                 f.metadata["unit"], describe(f.name).replace("|", "\\|")))
    return "\n".join(rows)


def example_toml() -> str:
    """A complete placemat.toml: every section and setting with its default, unit and meaning, grouped by section.
    It loads to the defaults. A setting whose default is no TOML value (unset) is a commented line."""
    import textwrap
    out = ["# placemat.toml: every setting, its unit, what it means and its default.",
           "# Written by `placemat settings --example`. Keep only the lines you change: a key set here is a decision",
           "# the project has made, and the nearest placemat.toml wins per key (built-in default < file < CLI flag).",
           ""]
    by_section: dict = {}
    for f in fields(Settings):
        if f.name == "sources":
            continue
        by_section.setdefault(split_key(f.name)[0], []).append(f)
    for section, fs in by_section.items():
        out += ["# " + "-" * 76, "# %s: %s" % (section, SECTIONS[section]), "# " + "-" * 76, "[%s]" % section, ""]
        subtables = []
        for f in fs:
            key = split_key(f.name)[1]
            default = _default_of(f)
            head = textwrap.wrap(describe(f.name), 108, initial_indent="# ", subsequent_indent="# ")
            note = "# unit: %s; default %s" % (f.metadata["unit"], _shown_default(default))
            if f.name in _SUBTABLES_BY_NAME:
                subtables.append((f, head, note))
                continue
            out += head + [note]
            out.append(("# %s = <unset>" % key) if default is None else "%s = %s" % (key, _toml_value(default)))
            out.append("")
        for f, head, note in subtables:
            out += head + [note, "[%s]" % f.name.replace("_", ".", 1), ""]
    return "\n".join(out).rstrip("\n") + "\n"
