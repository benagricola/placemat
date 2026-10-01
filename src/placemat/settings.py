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
from dataclasses import dataclass, field, fields, replace
import json
from pathlib import Path
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
# KiCad's own stderr noise. A project ADDS to this; it never replaces it.
DEFAULT_NOISE = (r"property\.h\(\d+\): assert",
                 r"Debug: Adding duplicate image handler",
                 r"swig/python detected a memory leak")

FILENAME = "placemat.toml"


@dataclass(frozen=True)
class Settings:
    """Resolved settings for one run. Frozen: a run is judged by one set."""
    # [rank] - how searched items are ordered
    rank_area: float = 0.7
    rank_pins: float = 0.3
    # [place] - the search
    place_radius: float = 3.0
    place_step: float = 0.2
    place_envelope: str = "courtyard"   # what a part claims: its courtyard, its pads, mask, silk and body, or both
    place_rotations: str = "all"        # a searched part with no rotation given: all four, or only its declared one
    place_bearing_step: float = 5.0     # degrees between the turns of rotations=Turns.ANY
    place_coarse_steps: int = 4
    place_coarse_from: float = 12.0
    place_refine_around: int = 3
    place_block_gap_step: float = 0.05
    place_block_gap_reach: float = 2.0
    place_escape_depth: float = 1.0     # how far each corridor out of a pad runs (escapes.py)
    place_escape_pads: int = 1          # a part keeps escapes for its pads when it has at least this many
    place_escape_via_step: float = 0.05  # the step a lane's via is searched along its lane at, from the row's end (lanes.py)
    place_escape_via_reach: float = 5.0  # how far past the row's end it is searched before the lane has no legal spot
    place_courtyard_touch: float = 0.0   # courtyards may touch, never overlap: KiCad counts touching polygons, and its are inside ours by half a stroke
    place_courtyard_polygon_share: float = 0.98   # a courtyard polygon covering less of its box than this is claimed as drawn, not as its box
    place_conflict_gap: float = 1.0
    place_fit_room: float = 10.0        # a fit frame's provisional room: how far round the decided content a searched item may go
    place_via_share: float = 1.0        # a carried via meeting another net's copper may share a same-net via this close (giveway.py); 0: never
    place_via_move: float = 0.5         # or move this far to clear it; 0: never
    place_via_move_step: float = 0.05   # the grid a via's move is searched on
    place_via_clear_cache: int = 4096   # a scan keeps this many placed vias' clear moves, each searched once
    place_drops_keep: float = 0.5       # the share of a pad's drops it keeps, rounded up, never fewer than one (Drops.MIN); a carried drop is dropped only while its pad keeps this share; 1: never
    place_edge_step: float = 0.05       # a part placed on a curved board edge is stepped in from the edge at this step until the keep-in holds it (placer.py)
    place_pocket_step: float = 0.5      # the raster a free-rectangle (pocket) search blocks the board at, least; an item's own step is used when coarser (layout.py)
    place_freedom_min_step: float = 0.2   # the least step a part's one-freedom search (along an edge, round a ring) walks at, mm; an item's own step is used when coarser
    place_cutout_step: float = 0.2      # the step a cutout is slid along a free axis at, mm
    place_cutout_angle_step: float = 0.5   # the step a cutout is turned round its centre at, degrees
    place_escape_cell: float = 0.05     # the grid a pad's path out is searched on, mm (escapes.py); a quarter of the narrowest track a fab offers
    place_split_min_group: int = 2      # the least members a group needs to count, in a cell's split finding (splits.py)
    # [copper]
    copper_chamfer: float = 1.0
    copper_pair_chamfer: float = 0.5
    copper_pair_via_step: float = 0.4
    copper_bridge_half: float = 1.1
    copper_finger_bridge_width: float = 1.0
    copper_finger_min_piece: float = 0.05   # a finger's piece between two bridges no longer than this is not drawn, mm
    copper_plane_inset: float = 0.4
    copper_plane_clearance: float = 0.2
    copper_plane_min_thickness: float = 0.2
    copper_pour_stroke: float = 0.2
    copper_cell_zones_under_planes: str = "drop"   # a stamped cell's zone the board's own plane covers: merged into it, or kept
    copper_tap_overlap: float = 0.005   # how far a tap's copper reaches over its pad's edge, mm: copper that only meets the pad along a line may not read as joined
    copper_microvia_drill: float = 0.1  # a micro via's (laser) drill, when the script gives none
    copper_straight_tolerance: float = 0.002   # a track leg whose ends differ less than this on one axis is drawn straight; measure --copper judges 0/45/90 by it
    # [write]
    write_split_groups: str = "lift"    # each cell's group nested in a module's: lifted to the top level (the module keeps its parts); "split" also takes out the parts placed apart; "keep" as generated
    write_keepout_drawings: str = "admitting"   # draw a keepout's outline and name (and height limit) on its Fab layer (or User.Comments): "admitting" (default) those that admit something, "all" every keepout, "none"
    write_keepout_line: float = 0.1    # a drawn keepout's outline stroke
    write_keepout_text: float = 0.8    # a drawn keepout's label height
    # [label]
    label_size: float = 1.0
    label_thickness: float = 0.15
    label_gap: float = 0.0
    # [geometry]
    geometry_arc_sag: float = 0.02
    geometry_index_cells: int = 16
    geometry_arc_error_nm: int = 5000
    geometry_cap_steps: int = 8         # segments round each half-circle end of a track's polygon (copper.py, native/src/giveway.rs)
    # [check]
    check_ambient_c: float = 100.0
    check_keep_out_mm: float = 2.0
    check_rise_c: float = 10.0
    check_neck_band: float = 0.1      # a current path's neck runs as far as its track stays within this fraction of the narrowest width
    check_zone_step: float = 0.05     # the cell a zone fill is rasterised at to measure its width on a load's route
    check_limits: dict = field(default_factory=dict)
    # [parts]
    parts_order_fields: tuple = ("Lcsc", "LCSC", "Mpn", "MPN")   # a placed part with none of these fields non-empty gets a "no order number" warning
    # [drc]
    drc_real_kinds: tuple = DEFAULT_REAL_KINDS
    drc_outstanding_kinds: tuple = DEFAULT_OUTSTANDING_KINDS
    drc_footprint_kinds: tuple = DEFAULT_FOOTPRINT_KINDS
    drc_refill_zones: bool = True
    # [explore] - the time-boxed search (explore.py)
    explore_slack: float = 0.25        # a drawn spot scores within this fraction of the item's best
    explore_swap: float = 0.2          # the chance two focused neighbours trade turns
    explore_rank_power: float = 1.0    # a drawn spot at rank r is weighted 1 / r ** this: higher keeps nearer the best
    explore_congestion_step: float = 0.05   # the worst RUDY cell ranks variants in steps of this; 0 leaves it out
    explore_jobs: int = 0              # worker processes; 0: the CPU count less one
    drc_severities: dict = field(default_factory=dict)   # KiCad rule -> error|warning|ignore, written into the board's project
    # [route]
    route_router_dir: str = ""          # "": fall back to $KRT_DIR, then the built-in
    route_quick: bool = True
    route_iterations: int | None = None
    route_plane_share: float = 0.9      # how much of the board's own outline a pour must cover to be guarded whole from other nets' tracks while routing
    # The router prices a straight step at 1000 and a turn at this per 90 degrees (a 45 half of it). Its own
    # default, 1000, makes a 45-degree kink worth 0.05 mm of path, and its routes stair-step; 20000 measured on
    # one measured six-layer board: 66.8% closure against 66.0%, 5.8 turns per 10 mm against 12.6, 10% less copper.
    route_turn_cost: int = 20000
    route_smoothing: bool = True        # the router's own octolinear smoothing, as it defaults
    route_router_args: tuple = ()       # more of route.py's own flags, appended to its passes (the island nets, the main pass)
    route_pair_router_args: tuple = ()  # more of route_diff.py's own flags, for the pair pass (the two take different flags)
    route_islands: tuple = ()           # nets with pours whose pads the pours do not reach, routed first and alone: "NET" or "NET=WIDTH" (mm)
    route_diff_pair_gap: float = 0.0    # mm between a pair's tracks; 0: the net class's
    route_diff_pair_width: float = 0.0  # mm, a pair's track width; 0: the net class's
    route_adopt_tolerance: float = 0.001   # mm: how far a kept pad may lie from where the parts' common motion puts it before adopted routes are dropped
    # [timeout] - seconds
    timeout_generate: int = 900
    timeout_drc: int = 600
    timeout_route: int = 3600
    timeout_render: int = 300
    # [noise] - added to DEFAULT_NOISE, never replacing it
    noise_patterns: tuple = ()
    # [best] - judging a run against the best of its family
    best_airwire_noise: float = 0.01
    best_crossing_noise: float = 0.02   # a fraction of the crossings, as airwire's: kicad-cli's ratsnest varies too
    # [score] - what each thing that can go wrong costs a run, in millimetres of wire (score.py)
    score_unplaced: float = 2000.0      # a part left unplaced, times its declared priority's multiplier
    score_priority_high: float = 2.0
    score_priority_default: float = 1.0
    score_priority_low: float = 0.5
    score_drc: float = 200.0            # a real DRC violation
    score_link_over: float = 20.0       # a millimetre of link past its limit, times the link's weight
    score_fixed: float = 200.0          # a decided item not legal where it was put
    score_copper: float = 200.0         # planned copper that meets another net, crosses a keepout or cannot bridge
    score_label: float = 50.0           # a label with a part on it
    score_setup: float = 0.0            # the same every run of a script: an undeclared part, a layer the board lacks
    score_crossing: float = 4.0         # a ratsnest crossing; the search weighs a candidate's crossings by it too
    score_crossing_plane: float = 0.0   # a crossing with a plane's or free net's airwire, as a share of score_crossing
    score_pair_crossing: float = 100.0  # a differential pair crossing itself: it must exchange sides to route coupled
    score_escape_crossed: float = 20.0  # two escapes from one part's pins crossing near its pin row
    score_escape_depth: float = 1.5     # the corridors' length the escape findings, and so the run score, are measured at
    score_escape_closed: float = 50.0   # a pad's last route toward what it connects to closed
    score_escape_walled: float = 400.0  # a pad with no route out at all
    score_escape_lane: float = 400.0    # a declared escape lane (board.escape) another net's pad, hole or copper blocks, or whose via has no spot
    score_congestion: float = 10.0      # explore: a step (explore.congestion_step) of the worst RUDY cell
    score_via_share: float = 1.0        # the search: a carried via that shares a same-net via
    score_via_move: float = 2.0         # a carried via that moves
    score_via_drop: float = 10.0        # a plane drop dropped
    score_push: float = 10.0            # a push: score.push times the modelled value over its limit, at the search
    score_via_shorten: float = 5.0      # a carried drop shortened to the plane's nearest layer instead of dropped: between move and drop
    # [solve] - the global pre-solve for the searched tier's hints
    solve_enabled: bool = False
    solve_iterations: int = 200
    solve_tolerance: float = 1e-6
    solve_rounds: int = 8
    solve_pull: float = 0.01            # the weak pull of every part toward the middle of the board, per unit spring
    solve_spread_pull: float = 0.01     # the first round's pull of each part toward its spread cell
    solve_spread_growth: float = 2.0    # the pull's growth each round after: round n pulls with spread_pull * growth ** n
    preview_converter: str = "rsvg-convert --width {width} -o {png} {svg}"   # SVG to PNG; {svg}, {png}, {width}
    preview_px_per_mm: float = 40.0     # the PNG's resolution: 40 px a millimetre shows a 0.1 mm gap as 4 px
    preview_model_edge: int = 1568      # px an image's long edge is scaled to before the reading model sees it
                                        # (an assumption about that model, not a fact placemat can know); 0: say nothing
    cleanup_enabled: bool = True        # after the searched tier, move and swap parts to shorten wire and links
    cleanup_passes: int = 2             # the module sweep: a third pass or a 0.25 mm step bought little for 2-3x the time
    cleanup_radius: float = 3.0
    cleanup_step: float = 0.5
    cleanup_swap_neighbours: int = 4    # each part is offered a swap with this many of its nearest movable neighbours
    cleanup_swap_radius: float = 1.0    # how far round the other's old spot each part of a swap is searched

    # [facts] - placemat's own record, not a board fact: never part of a run's id
    facts_confirmed: str = ""           # a digest of the facts last confirmed with `placemat facts --confirm`

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
        dict ordering. facts_confirmed is left out: it is placemat's own
        record of a user's confirmation, not a fact that changes a run, so
        confirming never gives a script a new run id."""
        out = {}
        for name in self.keys():
            if name == "facts_confirmed":
                continue
            v = getattr(self, name)
            out[name] = sorted(v.items()) if isinstance(v, dict) else (
                list(v) if isinstance(v, tuple) else v)
        return json.dumps(out, sort_keys=True, separators=(",", ":"))

    def with_sources(self, sources: dict) -> "Settings":
        return replace(self, sources=dict(sources))


# `[check.limits]` is the one sub-table: its section is two words.
_SUBTABLES = ("check.limits", "drc.severities")


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


# The router flags placemat sets on every pass: [route] router_args may not name them.
_ROUTER_OWNED = frozenset(("--nets", "--layers", "--escalation", "--keep-input-copper", "--turn-cost", "--smoothing",
                           "--no-smoothing", "--power-nets", "--power-nets-widths", "--max-iterations",
                           "--max-probe-iterations", "--json-out"))


class SettingsError(ValueError):
    """A placemat.toml that cannot be obeyed. A setting that quietly does
    nothing reads as though it is in force, so this is never a warning."""


# Keys with a fixed set of values.
_CHOICES = {"place_envelope": ("courtyard", "physical", "union"), "place_rotations": ("all", "declared"),
            "copper_cell_zones_under_planes": ("drop", "keep"), "write_split_groups": ("lift", "split", "keep"),
            "write_keepout_drawings": ("admitting", "all", "none")}

# Keys with a floor. A value at or below it is a setting that cannot work: a
# zero scan step never moves, a zero timeout never runs. Weights are absent
# from this table because weighting a dimension at nothing is a real choice.
_ABOVE_ZERO = frozenset((
    "place_radius", "place_step", "place_bearing_step", "place_coarse_from", "place_coarse_steps",
    "place_refine_around", "place_block_gap_step", "place_block_gap_reach", "place_escape_depth", "place_escape_via_step", "place_escape_via_reach", "place_edge_step", "place_pocket_step", "place_freedom_min_step", "place_cutout_step", "place_cutout_angle_step", "place_escape_cell", "geometry_cap_steps", "solve_spread_growth", "solve_pull", "score_escape_depth", "place_via_move_step", "place_via_clear_cache",
    "place_conflict_gap", "place_fit_room", "copper_bridge_half", "copper_finger_bridge_width", "copper_finger_min_piece",
    "copper_plane_min_thickness", "copper_pour_stroke", "copper_microvia_drill", "label_size",
    "label_thickness", "geometry_arc_sag", "geometry_index_cells",
    "geometry_arc_error_nm", "check_rise_c", "check_zone_step",
    "timeout_generate", "timeout_drc", "timeout_route", "timeout_render",
    "solve_iterations", "solve_tolerance", "solve_rounds", "cleanup_radius", "cleanup_step", "cleanup_swap_radius", "preview_px_per_mm",
    "route_plane_share", "route_adopt_tolerance", "place_courtyard_polygon_share", "write_keepout_line", "write_keepout_text"))
_AT_LEAST_ZERO = frozenset((
    "rank_area", "rank_pins", "place_drops_keep", "route_turn_cost", "place_courtyard_touch", "cleanup_passes", "cleanup_swap_neighbours", "preview_model_edge", "copper_chamfer", "best_airwire_noise",
    "best_crossing_noise", "score_unplaced", "score_priority_high", "score_priority_default", "score_priority_low",
    "score_drc", "score_link_over", "score_fixed", "score_copper", "score_label", "score_setup", "score_crossing",
    "score_crossing_plane", "score_escape_crossed", "score_escape_closed", "score_escape_walled", "score_escape_lane", "score_congestion",
    "copper_pair_chamfer", "copper_pair_via_step", "copper_plane_inset", "copper_straight_tolerance",
    "copper_plane_clearance", "label_gap", "check_keep_out_mm", "route_diff_pair_gap", "route_diff_pair_width",
    "score_pair_crossing", "copper_tap_overlap", "check_neck_band", "solve_spread_pull", "place_via_share", "place_via_move", "score_via_share",
    "score_via_move", "score_via_drop", "score_via_shorten", "score_push"))
# A floor of 2: below it a "group" can never be more than one part, which
# is not a group at all.
_AT_LEAST_TWO = frozenset(("place_split_min_group",))


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
                path, dotted, ", ".join(owned), "[route] turn_cost, smoothing, islands and route --iterations name them"))
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
    if name in _AT_LEAST_TWO and value < 2:
        raise SettingsError("%s: %s must be at least 2, not %r" % (path, dotted, value))


# Keys retired because they named a board fact: placemat.toml holds no
# board fact, and a project that still sets one is told where it moved.
_RETIRED = {
    "check_copper_oz": "the board's own copper weight, read per layer from its stackup",
    "route_layers": "each layer's role in the board's stackup (signal/mixed routes, F.Cu and B.Cu always)",
    "route_diff_pairs": "a net class's diff_pair_width/diff_pair_gap in the board's .zen",
}


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


def load(start, overrides=None) -> Settings:
    """The settings for a board: built-in defaults, then every placemat.toml
    from the filesystem root down to the board's own directory (so the nearest
    wins per key), then the CLI overrides."""
    values, sources = {}, {}
    for path in _files(start):
        try:
            data = tomllib.loads(path.read_text())
        except tomllib.TOMLDecodeError as e:
            raise SettingsError("%s is not valid TOML: %s" % (path, e))
        for name, value in _flatten(data, path).items():
            _validate(name, value, str(path))
            values[name] = value
            sources[name] = str(path)
    for name, value in (overrides or {}).items():
        if name not in set(Settings.keys()):
            raise SettingsError("%s is not a setting placemat has" % name)
        _validate(name, value, "flag")
        values[name] = value
        sources[name] = "flag"
    coerced = {name: _coerce(name, value) for name, value in values.items()}
    return Settings(**coerced).with_sources(sources)
