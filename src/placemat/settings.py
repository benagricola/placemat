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
    place_coarse_steps: int = 4
    place_coarse_from: float = 12.0
    place_refine_around: int = 3
    place_block_gap_step: float = 0.05
    place_block_gap_reach: float = 2.0
    place_courtyard_touch: float = 0.02
    place_conflict_gap: float = 1.0
    # [copper]
    copper_chamfer: float = 1.0
    copper_pair_chamfer: float = 0.5
    copper_pair_via_step: float = 0.4
    copper_bridge_half: float = 1.1
    copper_finger_bridge_width: float = 1.0
    copper_plane_inset: float = 0.4
    copper_plane_clearance: float = 0.2
    copper_plane_min_thickness: float = 0.2
    copper_pour_stroke: float = 0.2
    # [label]
    label_size: float = 1.0
    label_thickness: float = 0.15
    label_gap: float = 0.0
    # [geometry]
    geometry_arc_sag: float = 0.02
    geometry_index_cells: int = 16
    geometry_arc_error_nm: int = 5000
    # [check]
    check_ambient_c: float = 100.0
    check_keep_out_mm: float = 2.0
    check_rise_c: float = 10.0
    check_copper_oz: float = 1.0
    check_limits: dict = field(default_factory=dict)
    # [drc]
    drc_real_kinds: tuple = DEFAULT_REAL_KINDS
    drc_outstanding_kinds: tuple = DEFAULT_OUTSTANDING_KINDS
    drc_footprint_kinds: tuple = DEFAULT_FOOTPRINT_KINDS
    drc_refill_zones: bool = True
    # [route]
    route_router_dir: str = ""          # "": fall back to $KRT_DIR, then the built-in
    route_quick: bool = True
    route_iterations: int | None = None
    route_layers: tuple | None = None
    # [timeout] - seconds
    timeout_generate: int = 900
    timeout_drc: int = 600
    timeout_route: int = 3600
    timeout_render: int = 300
    # [noise] - added to DEFAULT_NOISE, never replacing it
    noise_patterns: tuple = ()
    # [best] - judging a run against the best of its family
    best_airwire_noise: float = 0.01
    # [solve] - the global pre-solve for the searched tier's hints
    solve_enabled: bool = False
    solve_iterations: int = 200
    solve_tolerance: float = 1e-6
    solve_rounds: int = 8
    cleanup_enabled: bool = True        # after the searched tier, move and swap parts to shorten wire and links
    cleanup_passes: int = 2             # the module sweep: a third pass or a 0.25 mm step bought little for 2-3x the time
    cleanup_radius: float = 3.0
    cleanup_step: float = 0.5

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
        dict ordering."""
        out = {}
        for name in self.keys():
            v = getattr(self, name)
            out[name] = sorted(v.items()) if isinstance(v, dict) else (
                list(v) if isinstance(v, tuple) else v)
        return json.dumps(out, sort_keys=True, separators=(",", ":"))

    def with_sources(self, sources: dict) -> "Settings":
        return replace(self, sources=dict(sources))


# `[check.limits]` is the one sub-table: its section is two words.
_SUBTABLES = ("check.limits",)


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


class SettingsError(ValueError):
    """A placemat.toml that cannot be obeyed. A setting that quietly does
    nothing reads as though it is in force, so this is never a warning."""


# Keys with a fixed set of values.
_CHOICES = {"place_envelope": ("courtyard", "physical", "union")}

# Keys with a floor. A value at or below it is a setting that cannot work: a
# zero scan step never moves, a zero timeout never runs. Weights are absent
# from this table because weighting a dimension at nothing is a real choice.
_ABOVE_ZERO = frozenset((
    "place_radius", "place_step", "place_coarse_from", "place_coarse_steps",
    "place_refine_around", "place_block_gap_step", "place_block_gap_reach",
    "place_conflict_gap", "copper_bridge_half", "copper_finger_bridge_width",
    "copper_plane_min_thickness", "copper_pour_stroke", "label_size",
    "label_thickness", "geometry_arc_sag", "geometry_index_cells",
    "geometry_arc_error_nm", "check_rise_c", "check_copper_oz",
    "timeout_generate", "timeout_drc", "timeout_route", "timeout_render",
    "solve_iterations", "solve_tolerance", "solve_rounds", "cleanup_radius", "cleanup_step"))
_AT_LEAST_ZERO = frozenset((
    "rank_area", "rank_pins", "place_courtyard_touch", "cleanup_passes", "copper_chamfer", "best_airwire_noise",
    "copper_pair_chamfer", "copper_pair_via_step", "copper_plane_inset",
    "copper_plane_clearance", "label_gap", "check_keep_out_mm"))


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
    if name in _CHOICES and value not in _CHOICES[name]:
        raise SettingsError("%s: %s must be %s, not %r" % (
            path, dotted, ", ".join(_CHOICES[name][:-1]) + " or " + _CHOICES[name][-1], value))
    if name in _ABOVE_ZERO and not value > 0:
        raise SettingsError("%s: %s must be greater than 0, not %r" % (path, dotted, value))
    if name in _AT_LEAST_ZERO and value < 0:
        raise SettingsError("%s: %s may not be negative, not %r" % (path, dotted, value))


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
