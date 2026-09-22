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


def _flatten(data: dict, path) -> dict:
    """A parsed TOML document as {attribute name: value}. Sub-tables named in
    _SUBTABLES are one value; any other nested table is a section."""
    out = {}
    for section, body in data.items():
        if not isinstance(body, dict):
            raise ValueError("%s: %r is a bare value; every setting lives in a "
                             "section, e.g. [place]\n%s = ..." % (path, section, section))
        for key, value in body.items():
            full = "%s.%s" % (section, key)
            if isinstance(value, dict):
                out[join_key(full, "")] = dict(value)
            else:
                out[join_key(section, key)] = value
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
            raise ValueError("%s is not valid TOML: %s" % (path, e))
        for name, value in _flatten(data, path).items():
            values[name] = value
            sources[name] = str(path)
    for name, value in (overrides or {}).items():
        values[name] = value
        sources[name] = "flag"
    coerced = {name: _coerce(name, value) for name, value in values.items()}
    return Settings(**coerced).with_sources(sources)
