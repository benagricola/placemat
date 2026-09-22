# placemat.toml Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give placemat one config file, `placemat.toml`, that holds every behavioural constant, with precedence default < file < CLI flag.

**Architecture:** A frozen `Settings` dataclass with one flat attribute per `[section] key` (derived as `section_key`), loaded by walking up from the board directory and merging nearest-wins. Objects that exist carry it (`Board.settings`, `Occupancy.settings`); deep geometry helpers reached through frozen value objects read `settings.active()`, bound for the run by a contextmanager, the same idiom `context.bind` uses for `board`.

**Tech Stack:** Python 3.12 (`tomllib` is stdlib - no new dependency), pytest, dataclasses.

**Spec:** `docs/superpowers/specs/2026-09-22-placemat-toml-design.md`

## Global Constraints

- Python floor is 3.12 (`pyproject.toml`); `tomllib` is stdlib, do not add a TOML dependency.
- `pcbnew` may be imported only under `src/placemat/kicad/`. Everything else is pure Python and must be unit-testable without KiCad.
- Precedence is exactly: built-in default < `placemat.toml` (nearest file wins per key) < CLI flag. No flag is removed; no setting becomes flag-only.
- An unknown section, unknown key, wrong type or out-of-range value is an **error** naming the file and the key, never a warning and never silence.
- Every built-in default must equal the value placemat uses today, so a project with no `placemat.toml` behaves identically.
- ASCII only in all prose, comments and commit messages: no em dashes, no en dashes, no unicode arrows, straight quotes.
- Commit messages must contain no reference to Claude, Anthropic, or a session URL.
- Attribute naming is derived, not hand-mapped: `[section] key` is always the attribute `section_key`.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/placemat/settings.py` (create) | `Settings` dataclass, defaults, TOML load, walk-up merge, validation, `sources`, canonical `json()`, `bind()`/`active()` |
| `tests/test_settings.py` (create) | Everything in `settings.py`, without KiCad |
| `src/placemat/report.py` (modify) | `run_id` takes `settings_json` |
| `src/placemat/runner.py` (modify) | Build, bind and hash the settings; use `[timeout]` |
| `src/placemat/cli.py` (modify) | `placemat settings` command; route CLI overrides into `Settings` |
| `src/placemat/layout.py` (modify) | `Board` carries settings; verb defaults become `None` |
| `src/placemat/occupancy.py` (modify) | Carries settings; `TOUCH`/`_GAP` from them |
| `src/placemat/placer.py` (modify) | Reads `occ.settings` for the scan and block constants |
| `src/placemat/copper.py` (modify) | `resolve_bridges` takes `bridge_half` |
| `src/placemat/cutouts.py` (modify) | `flatten_arc` and `SpatialIndex` read `settings.active()` |
| `src/placemat/checks.py` (modify) | Defaults sourced from `Settings` at the call site |
| `src/placemat/kicad/drc.py` (modify) | Violation classes and refill from settings |
| `src/placemat/kicad/route.py` (modify) | Router dir, timeout, quick, iterations, layers |
| `src/placemat/kicad/read.py` (modify) | `arc_error_nm` threaded through this file |
| `src/placemat/kicad/quiet.py` (modify) | `_is_noise` adds `settings.active().noise_patterns` |
| `src/placemat/kicad/write.py` (modify) | Render timeout from settings |
| `skills/placemat/references/api.md` (modify) | Settings section; verb defaults cite `[section].key` |
| `skills/placemat/SKILL.md` (modify) | Run `placemat settings` before reading a board's numbers |

---

## Task 1: The Settings object

**Files:**
- Create: `src/placemat/settings.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Settings` (frozen dataclass, one attribute per `section_key`), `Settings.json() -> str`, `Settings.source_of(key) -> str`, `bind(settings)` contextmanager, `active() -> Settings`, `DEFAULT_REAL_KINDS`, `DEFAULT_OUTSTANDING_KINDS`, `DEFAULT_NOISE`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_settings.py
"""placemat.toml: one home for every behavioural constant, and the rules
for where a value came from."""
import json

import pytest

from placemat import settings as S


def test_defaults_are_todays_values():
    s = S.Settings()
    assert s.rank_area == 0.7 and s.rank_pins == 0.3
    assert s.place_step == 0.2 and s.place_radius == 3.0
    assert s.place_coarse_steps == 4 and s.place_coarse_from == 12.0
    assert s.place_refine_around == 3
    assert s.place_block_gap_step == 0.05 and s.place_block_gap_reach == 2.0
    assert s.place_courtyard_touch == 0.02 and s.place_conflict_gap == 1.0
    assert s.copper_chamfer == 1.0 and s.copper_bridge_half == 1.1
    assert s.copper_plane_inset == 0.4 and s.copper_pour_stroke == 0.2
    assert s.label_size == 1.0 and s.label_thickness == 0.15
    assert s.geometry_arc_sag == 0.02 and s.geometry_index_cells == 16
    assert s.geometry_arc_error_nm == 5000
    assert s.check_ambient_c == 100.0 and s.check_keep_out_mm == 2.0
    assert s.drc_refill_zones is True
    assert s.timeout_generate == 900 and s.timeout_drc == 600


def test_every_attribute_maps_to_a_section_and_key():
    """The TOML shape is derived, never hand-mapped: [place] step is place_step."""
    for name in S.Settings.keys():
        assert "_" in name, name
        section, key = S.split_key(name)
        assert S.join_key(section, key) == name


def test_nothing_bound_gives_the_defaults():
    assert S.active() == S.Settings()


def test_bind_scopes_a_settings_and_restores_it():
    mine = S.Settings(place_step=0.05)
    with S.bind(mine):
        assert S.active().place_step == 0.05
    assert S.active().place_step == 0.2


def test_json_is_canonical_and_ignores_sources():
    a = S.Settings(place_step=0.1)
    b = S.Settings(place_step=0.1, sources={"place_step": "somewhere.toml"})
    assert a.json() == b.json()
    assert json.loads(a.json())["place_step"] == 0.1


def test_json_differs_when_a_value_differs():
    assert S.Settings(place_step=0.1).json() != S.Settings(place_step=0.2).json()


def test_source_of_defaults_to_the_word_default():
    assert S.Settings().source_of("place_step") == "default"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_settings.py -x -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'placemat.settings'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/placemat/settings.py
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

# The violation classes a board is judged by. A project may say otherwise.
DEFAULT_REAL_KINDS = ("clearance", "shorting_items", "track_width", "annular_width",
                      "hole_clearance", "hole_to_hole", "courtyards_overlap",
                      "copper_edge_clearance")
DEFAULT_OUTSTANDING_KINDS = ("via_dangling", "track_dangling", "isolated_copper")
# KiCad's own stderr noise. A project ADDS to this; it never replaces it.
DEFAULT_NOISE = (r"property\.h\(\d+\): assert",
                 r"Debug: Adding duplicate image handler",
                 r"swig/python detected a memory leak")


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
    route_router_dir: str = ""              # "": fall back to $KRT_DIR, then ~/work/KiCadRoutingTools
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_settings.py -x -q`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/placemat/settings.py tests/test_settings.py
git commit -m "Settings: every behavioural constant, with a scoped binding"
```

---

## Task 2: Loading placemat.toml, merged nearest-wins

**Files:**
- Modify: `src/placemat/settings.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Consumes: `Settings`, `join_key` from Task 1.
- Produces: `load(start, overrides=None) -> Settings`, `FILENAME = "placemat.toml"`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_settings.py

def _toml(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_no_file_anywhere_gives_the_defaults(tmp_path):
    board = tmp_path / "boards" / "main"
    board.mkdir(parents=True)
    s = S.load(board)
    assert s == S.Settings()
    assert all(s.source_of(k) == "default" for k in S.Settings.keys())


def test_a_file_two_levels_up_is_found(tmp_path):
    _toml(tmp_path / "placemat.toml", "[place]\nstep = 0.05\n")
    board = tmp_path / "boards" / "main"
    board.mkdir(parents=True)
    s = S.load(board)
    assert s.place_step == 0.05
    assert s.source_of("place_step") == str(tmp_path / "placemat.toml")
    assert s.place_radius == 3.0 and s.source_of("place_radius") == "default"


def test_the_nearest_file_wins_per_key_and_the_outer_one_still_contributes(tmp_path):
    _toml(tmp_path / "placemat.toml", "[place]\nstep = 0.05\nradius = 9.0\n")
    board = tmp_path / "boards" / "main"
    _toml(board / "placemat.toml", "[place]\nstep = 0.01\n")
    s = S.load(board)
    assert s.place_step == 0.01                       # the nearest file
    assert s.place_radius == 9.0                      # only the outer file has it
    assert s.source_of("place_step") == str(board / "placemat.toml")
    assert s.source_of("place_radius") == str(tmp_path / "placemat.toml")


def test_a_sub_table_loads(tmp_path):
    _toml(tmp_path / "placemat.toml", '[check.limits]\n"hot-loop" = 20.0\n')
    s = S.load(tmp_path)
    assert s.check_limits == {"hot-loop": 20.0}


def test_a_list_valued_key_loads_as_a_tuple(tmp_path):
    _toml(tmp_path / "placemat.toml", '[drc]\nreal_kinds = ["clearance"]\n')
    s = S.load(tmp_path)
    assert s.drc_real_kinds == ("clearance",)


def test_a_file_is_read_once_even_when_the_start_is_the_file_s_own_directory(tmp_path):
    _toml(tmp_path / "placemat.toml", "[place]\nstep = 0.05\n")
    assert S.load(tmp_path).place_step == 0.05
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_settings.py -x -q`
Expected: FAIL with `AttributeError: module 'placemat.settings' has no attribute 'load'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/placemat/settings.py` (imports first: add `from pathlib import Path`, `import tomllib`):

```python
FILENAME = "placemat.toml"


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
                             "section, e.g. [place]\\n%s = ..." % (path, section, section))
        for key, value in body.items():
            full = "%s.%s" % (section, key)
            if isinstance(value, dict):
                if full not in _SUBTABLES:
                    raise ValueError("%s: [%s] is not a section placemat knows" % (path, full))
                out[join_key(full, "")] = dict(value)
            else:
                out[join_key(section, key)] = value
    return out


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


def _coerce(name: str, value):
    """A TOML list becomes the tuple the field is declared as."""
    declared = {f.name: f.type for f in fields(Settings)}.get(name)
    if declared is not None and "tuple" in str(declared) and isinstance(value, list):
        return tuple(value)
    return value
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_settings.py -x -q`
Expected: PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add src/placemat/settings.py tests/test_settings.py
git commit -m "placemat.toml is found by walking up, and merges nearest-wins"
```

---

## Task 3: Validation - an unknown key is an error

**Files:**
- Modify: `src/placemat/settings.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Consumes: `load`, `Settings.keys()` from Tasks 1-2.
- Produces: `SettingsError(ValueError)`; `load` raises it.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_settings.py

def test_an_unknown_section_is_an_error_naming_the_file(tmp_path):
    _toml(tmp_path / "placemat.toml", "[plaec]\nstep = 0.05\n")
    with pytest.raises(S.SettingsError) as e:
        S.load(tmp_path)
    assert "placemat.toml" in str(e.value) and "plaec" in str(e.value)


def test_an_unknown_key_is_an_error_suggesting_the_nearest(tmp_path):
    _toml(tmp_path / "placemat.toml", "[place]\nstepp = 0.05\n")
    with pytest.raises(S.SettingsError) as e:
        S.load(tmp_path)
    assert "place.stepp" in str(e.value) and "place.step" in str(e.value)


def test_a_wrong_type_is_an_error(tmp_path):
    _toml(tmp_path / "placemat.toml", '[place]\nstep = "small"\n')
    with pytest.raises(S.SettingsError) as e:
        S.load(tmp_path)
    assert "place.step" in str(e.value) and "number" in str(e.value)


def test_a_value_under_its_floor_is_an_error(tmp_path):
    _toml(tmp_path / "placemat.toml", "[place]\nstep = 0.0\n")
    with pytest.raises(S.SettingsError) as e:
        S.load(tmp_path)
    assert "place.step" in str(e.value) and "greater than 0" in str(e.value)


def test_a_negative_weight_is_an_error(tmp_path):
    _toml(tmp_path / "placemat.toml", "[rank]\narea = -1.0\n")
    with pytest.raises(S.SettingsError):
        S.load(tmp_path)


def test_a_zero_weight_is_allowed(tmp_path):
    """Weighting pins at nothing is a legitimate choice; weighting a step at
    nothing is a scan that never moves."""
    _toml(tmp_path / "placemat.toml", "[rank]\npins = 0.0\n")
    assert S.load(tmp_path).rank_pins == 0.0


def test_an_error_in_an_outer_file_still_names_that_file(tmp_path):
    _toml(tmp_path / "placemat.toml", "[place]\nstepp = 1\n")
    board = tmp_path / "boards" / "main"
    _toml(board / "placemat.toml", "[place]\nstep = 0.01\n")
    with pytest.raises(S.SettingsError) as e:
        S.load(board)
    assert str(tmp_path / "placemat.toml") in str(e.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_settings.py -x -q`
Expected: FAIL with `AttributeError: module 'placemat.settings' has no attribute 'SettingsError'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/placemat/settings.py`:

```python
class SettingsError(ValueError):
    """A placemat.toml that cannot be obeyed. A setting that quietly does
    nothing reads as though it is in force, so this is never a warning."""


# Keys with a floor. A value at or below it is a setting that cannot work:
# a zero scan step never moves, a zero timeout never runs. Weights are absent
# from this table because weighting a dimension at nothing is a real choice.
_ABOVE_ZERO = ("place_radius", "place_step", "place_coarse_from", "place_coarse_steps",
               "place_refine_around", "place_block_gap_step", "place_block_gap_reach",
               "place_conflict_gap", "copper_bridge_half", "copper_finger_bridge_width",
               "copper_plane_min_thickness", "copper_pour_stroke", "label_size",
               "label_thickness", "geometry_arc_sag", "geometry_index_cells",
               "geometry_arc_error_nm", "check_rise_c", "check_copper_oz",
               "timeout_generate", "timeout_drc", "timeout_route", "timeout_render")
_AT_LEAST_ZERO = ("rank_area", "rank_pins", "place_courtyard_touch", "copper_chamfer",
                  "copper_pair_chamfer", "copper_pair_via_step", "copper_plane_inset",
                  "copper_plane_clearance", "label_gap", "check_keep_out_mm")


def _nearest(name: str) -> str:
    """The valid key closest to a mistyped one, for the error message."""
    import difflib
    dotted = ["%s.%s" % split_key(k) for k in Settings.keys()]
    close = difflib.get_close_matches(name, dotted, n=1, cutoff=0.5)
    return close[0] if close else ""


def _validate(name: str, value, path: str):
    section, key = split_key(name)
    dotted = "%s.%s" % (section, key)
    declared = {f.name: f.type for f in fields(Settings)}[name]
    text = str(declared)
    if "float" in text and not isinstance(value, (int, float)) or isinstance(value, bool) and "bool" not in text:
        raise SettingsError("%s: %s must be a number, not %r" % (path, dotted, value))
    if "int" in text and "float" not in text and not isinstance(value, int):
        raise SettingsError("%s: %s must be a whole number, not %r" % (path, dotted, value))
    if "bool" in text and not isinstance(value, bool):
        raise SettingsError("%s: %s must be true or false, not %r" % (path, dotted, value))
    if "tuple" in text and not isinstance(value, (list, tuple)):
        raise SettingsError("%s: %s must be a list, not %r" % (path, dotted, value))
    if "dict" in text and not isinstance(value, dict):
        raise SettingsError("%s: %s must be a table, not %r" % (path, dotted, value))
    if name in _ABOVE_ZERO and not value > 0:
        raise SettingsError("%s: %s must be greater than 0, not %r" % (path, dotted, value))
    if name in _AT_LEAST_ZERO and value < 0:
        raise SettingsError("%s: %s may not be negative, not %r" % (path, dotted, value))
```

Then replace `_flatten`'s unknown-name handling and `load`'s coercion so both
check. In `_flatten`, after computing `full`/`name`, raise when the name is not
a field; in `load`, call `_validate` for every value:

```python
def _flatten(data: dict, path) -> dict:
    out = {}
    known = set(Settings.keys())
    sections = {split_key(k)[0] for k in known} | {s.split(".")[0] for s in _SUBTABLES}
    for section, body in data.items():
        if not isinstance(body, dict):
            raise SettingsError("%s: %r is a bare value; every setting lives in a "
                                "section, e.g. [place]\n%s = ..." % (path, section, section))
        if section not in sections:
            raise SettingsError("%s: [%s] is not a section placemat knows; it has %s"
                                % (path, section, ", ".join(sorted(sections))))
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
```

and in `load`, inside the file loop:

```python
        for name, value in _flatten(data, path).items():
            _validate(name, value, str(path))
            values[name] = value
            sources[name] = str(path)
```

and for the overrides:

```python
    for name, value in (overrides or {}).items():
        if name not in set(Settings.keys()):
            raise SettingsError("%s is not a setting placemat has" % name)
        _validate(name, value, "flag")
        values[name] = value
        sources[name] = "flag"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_settings.py -x -q`
Expected: PASS (20 tests)

- [ ] **Step 5: Commit**

```bash
git add src/placemat/settings.py tests/test_settings.py
git commit -m "A placemat.toml that cannot be obeyed is an error, not silence"
```

---

## Task 4: run_id takes the settings, and the runner binds them

**Files:**
- Modify: `src/placemat/report.py:36-48`, `src/placemat/runner.py`
- Test: `tests/test_report.py`, `tests/test_settings.py`

**Interfaces:**
- Consumes: `Settings.json()` from Task 1, `load` from Task 2.
- Produces: `run_id(script_text, board_bytes, tool_version, settings_json="")`; `runner.run` binds the settings for the whole run and records `rec.paths["settings"]`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_report.py

def test_the_settings_change_the_run_id():
    """A setting that changes the board must change the id: the runner
    rmtrees a run directory whose id matches, so a collision destroys the
    previous run's route/."""
    from placemat.report import run_id
    from placemat.settings import Settings
    same = dict(script_text="board.size(1, 1)\n", board_bytes=b"pcb", tool_version="0.2.0-dev")
    a = run_id(**same, settings_json=Settings().json())
    b = run_id(**same, settings_json=Settings().json())
    c = run_id(**same, settings_json=Settings(place_step=0.05).json())
    assert a == b and a != c


def test_run_id_without_settings_is_still_stable():
    from placemat.report import run_id
    same = dict(script_text="s", board_bytes=b"p", tool_version="v")
    assert run_id(**same) == run_id(**same)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_report.py -x -q`
Expected: FAIL with `TypeError: run_id() got an unexpected keyword argument 'settings_json'`

- [ ] **Step 3: Write minimal implementation**

In `src/placemat/report.py`, replace `run_id`:

```python
def run_id(script_text: str, board_bytes: bytes, tool_version: str, settings_json: str = "") -> str:
    """A run is named by a short hash of everything that decides its result:
    the script, the generated board it starts from, the tool version, and the
    resolved settings. Same inputs, same id; a label is only an alias for one.

    The settings are in the hash because a rerun with a matching id replaces
    its run directory, so a setting that changed the board without changing
    the id would destroy the previous run."""
    import hashlib
    h = hashlib.sha256()
    for part in (tool_version.encode(), script_text.encode(), board_bytes, settings_json.encode()):
        h.update(part)
        h.update(b"\0")
    return h.hexdigest()[:8]
```

In `src/placemat/runner.py`, after `src = find_board(script)` near the top of
`run()`, build the settings and bind them round the whole body. Add the import
`from . import settings as settings_mod` at the top, then:

```python
    src = find_board(script)
    resolved = settings_mod.load(src.board_dir, overrides=overrides or {})
    with settings_mod.bind(resolved):
        return _run(script, src, resolved, label=label, fresh=fresh, render=render, drc=drc,
                    quiet=quiet, verbose=verbose, route=route, route_quick=route_quick,
                    route_exclude=route_exclude, keep_going=keep_going)
```

Rename the existing body to `_run(script, src, cfg, ...)`, add `overrides=None`
to `run`'s signature, and inside `_run` replace the id line:

```python
        rid = run_id(script.read_text(), src.pcb.read_bytes(), __version__, cfg.json())
```

and record where the settings came from:

```python
        rec.paths["settings"] = cfg.sources.get("place_step", "default")
```

Replace that last line with the full map instead, so the record says every
source:

```python
        rec.paths["settings_files"] = sorted({v for v in cfg.sources.values() if v not in ("default", "flag")})
```

Use `cfg.timeout_generate` in `generate()` (pass it in as an argument) in place
of the literal `900`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_report.py tests/test_settings.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/placemat/report.py src/placemat/runner.py tests/test_report.py
git commit -m "The resolved settings join the run id"
```

---

## Task 5: placemat settings, and the CLI overrides

**Files:**
- Modify: `src/placemat/cli.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Consumes: `load`, `Settings.source_of` from Tasks 1-3.
- Produces: `cli.cmd_settings(args)`; `cli.overrides_from(args) -> dict`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_settings.py

def test_a_flag_beats_the_file_and_the_source_says_so(tmp_path):
    _toml(tmp_path / "placemat.toml", "[check]\nambient_c = 85.0\n")
    s = S.load(tmp_path, overrides={"check_ambient_c": 60.0})
    assert s.check_ambient_c == 60.0 and s.source_of("check_ambient_c") == "flag"


def test_a_flag_left_off_falls_to_the_file(tmp_path):
    _toml(tmp_path / "placemat.toml", "[check]\nambient_c = 85.0\n")
    s = S.load(tmp_path, overrides={})
    assert s.check_ambient_c == 85.0


def test_overrides_from_args_only_carries_what_was_given():
    import argparse
    from placemat import cli
    args = argparse.Namespace(ambient=None, keep_out=2.5, rise=None, copper_oz=None, limit=[])
    assert cli.overrides_from(args) == {"check_keep_out_mm": 2.5}


def test_overrides_from_args_reads_limit_pairs():
    import argparse
    from placemat import cli
    args = argparse.Namespace(ambient=None, keep_out=None, rise=None, copper_oz=None,
                              limit=["hot-loop=20"])
    assert cli.overrides_from(args) == {"check_limits": {"hot-loop": 20.0}}


def test_the_settings_command_prints_every_key_and_its_source(tmp_path, capsys):
    import argparse
    from placemat import cli
    _toml(tmp_path / "placemat.toml", "[place]\nstep = 0.05\n")
    args = argparse.Namespace(where=str(tmp_path), json=False)
    assert cli.cmd_settings(args) == 0
    out = capsys.readouterr().out
    assert "place.step" in out and "0.05" in out and "placemat.toml" in out
    assert "rank.area" in out and "default" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_settings.py -x -q -k "flag or overrides or settings_command"`
Expected: FAIL with `AttributeError: module 'placemat.cli' has no attribute 'overrides_from'`

- [ ] **Step 3: Write minimal implementation**

In `src/placemat/cli.py`, add the subparser inside `parser()`:

```python
    st = sub.add_parser("settings", help="every resolved setting, its value and the file it came from")
    st.add_argument("where", nargs="?", default=".", help="a layout script or a board directory (default: here)")
    st.add_argument("--json", action="store_true")
```

and register it in `main`'s dispatch table as `"settings": cmd_settings`.

Add the two functions:

```python
def overrides_from(args) -> dict:
    """The settings a command's flags set, and only those: a flag left off
    falls to placemat.toml, and a key absent from that falls to the default."""
    out = {}
    for flag, name in (("ambient", "check_ambient_c"), ("keep_out", "check_keep_out_mm"),
                       ("rise", "check_rise_c"), ("copper_oz", "check_copper_oz")):
        value = getattr(args, flag, None)
        if value is not None:
            out[name] = value
    limits = {}
    for item in getattr(args, "limit", None) or []:
        name, _, value = item.partition("=")
        limits[name] = float(value)
    if limits:
        out["check_limits"] = limits
    return out


def cmd_settings(args) -> int:
    from .settings import load, Settings, split_key
    from .project import find_board
    p = Path(args.where)
    start = p if p.is_dir() else find_board(p).board_dir
    s = load(start)
    if args.json:
        console.data(json.dumps({k: {"value": _plain(getattr(s, k)), "source": s.source_of(k)}
                                 for k in Settings.keys()}, indent=2, sort_keys=True))
        return 0
    for name in Settings.keys():
        section, key = split_key(name)
        console.say("settings", "%-28s %-24s %s" % (
            "%s.%s" % (section, key), _show(getattr(s, name)), s.source_of(name)))
    return 0


def _plain(v):
    return list(v) if isinstance(v, tuple) else v


def _show(v) -> str:
    if isinstance(v, (tuple, list)):
        return "[%d]" % len(v)
    if isinstance(v, dict):
        return "{%d}" % len(v)
    return "%s" % (v,)
```

Wire the overrides into `cmd_run` and `cmd_check`:

```python
def cmd_run(args) -> int:
    from .runner import run
    result = run(args.script, label=args.label, fresh=args.fresh, render=not args.no_render,
                 drc=not args.no_drc, quiet=args.quiet or args.json, verbose=args.verbose,
                 route=args.route, route_quick=not args.route_full, route_exclude=args.route_exclude,
                 keep_going=args.keep_going, overrides=overrides_from(args))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_settings.py -q && .venv/bin/python -m placemat settings --help`
Expected: PASS, and the help text prints

- [ ] **Step 5: Commit**

```bash
git add src/placemat/cli.py tests/test_settings.py
git commit -m "placemat settings: every value, and the file it came from"
```

---

## Task 6: [place] reaches the occupancy and the placer

**Files:**
- Modify: `src/placemat/occupancy.py:64-67,88-96`, `src/placemat/placer.py:101-120,415,489-500`, `src/placemat/layout.py:512-544,1735-1740`
- Test: `tests/test_settings_wiring.py` (create)

**Interfaces:**
- Consumes: `Settings` from Task 1.
- Produces: `Board(geometry, ..., settings=Settings())`, `Board.settings`; `Occupancy(geometry, ..., settings=Settings())`, `Occupancy.settings`; `placer.scan` and `layout_block` read `occ.settings`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_settings_wiring.py
"""A setting reaches the code that uses it. Each test changes one value and
asserts the behaviour it governs, rather than that the attribute exists."""
from placemat.layout import Board
from placemat.occupancy import Occupancy
from placemat.placement import Placement
from placemat.settings import Settings
from placemat.values import Face, Location, Part
from tests.fixtures import board_geometry, footprint


def _geom():
    return board_geometry([footprint("U1", 10, 10, w=4, h=2, inst="u1", nets=("A", "B")),
                           footprint("R1", 30, 30, w=2, h=1, inst="r1", nets=("B", "C"))],
                          width=60, height=60)


def test_the_board_carries_its_settings_and_hands_them_to_the_occupancy():
    s = Settings(place_step=0.05)
    b = Board(_geom(), edge_margin=1.0, settings=s)
    assert b.settings is s
    plan = b.resolve()
    assert plan.occupancy.settings is s


def test_a_default_board_gets_the_default_settings():
    b = Board(_geom(), edge_margin=1.0)
    assert b.settings == Settings()


def test_courtyard_touch_decides_whether_two_courtyards_overlap():
    """Two courtyards inside `place.courtyard_touch` of each other are packing,
    not a collision. Raise the tolerance and a real overlap reads as touching."""
    g = _geom()
    tight = Occupancy(g, edge_margin=0.0, settings=Settings(place_courtyard_touch=0.02))
    loose = Occupancy(g, edge_margin=0.0, settings=Settings(place_courtyard_touch=5.0))
    u1 = g.footprint("U1")
    onto = Placement(Location(30.0, 30.0), 0.0, Face.FRONT)     # right on R1
    assert tight.legal(u1, onto) is not None
    assert loose.legal(u1, onto) is None


def test_the_scan_step_is_the_declared_one():
    from placemat.placer import scan
    g = _geom()
    occ = Occupancy(g, edge_margin=0.0, settings=Settings())
    u1 = g.footprint("U1")
    coarse = scan(occ, u1, Placement(Location(20, 20), 0, Face.FRONT), radius=1.0, step=1.0)
    fine = scan(occ, u1, Placement(Location(20, 20), 0, Face.FRONT), radius=1.0, step=0.25)
    assert fine.tried > coarse.tried
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_settings_wiring.py -x -q`
Expected: FAIL with `TypeError: Board.__init__() got an unexpected keyword argument 'settings'`

- [ ] **Step 3: Write minimal implementation**

`occupancy.py`: import `from .settings import Settings`; add the parameter and
keep it; replace the two module constants at the use sites.

```python
    def __init__(self, geometry: BoardGeometry, edge_margin: float = 0.0, board_box: Box | None = None,
                 vias_block_courtyards: bool = False, board_shape=None, board_cutouts=None,
                 settings: Settings | None = None):
        self.settings = settings if settings is not None else Settings()
        self._gap = self.settings.place_conflict_gap
        self._touch = self.settings.place_courtyard_touch
```

Replace every `_GAP` in the file with `self._gap` and `_TOUCH` with
`self._touch`. `TOUCH` stays exported at its default for the tests that import
it; `_GAP`/`_TOUCH` module constants are deleted.

`placer.py`: read from the occupancy in `scan` and `scan_block`:

```python
    cfg = occ.settings
    if score is None or radius / step < cfg.place_coarse_from:
        ...
        coarse = step * cfg.place_coarse_steps
        ...
            for _, _, _, cand in legal[:cfg.place_refine_around]:
```

and in `layout_block`:

```python
        step_mm, reach = occ.settings.place_block_gap_step, occ.settings.place_block_gap_reach
        gaps = [spec.gap] if spec.gap is not None else [round(g * step_mm, 6)
                                                        for g in range(int(reach / step_mm) + 1)]
```

`layout.py`: `Board.__init__` gains `settings: Settings | None = None`, stores
`self.settings = settings if settings is not None else Settings()`, and
`resolve()` passes it:

```python
        occ = Occupancy(self.geometry, self.edge_margin, board_box=self._outline,
                        board_shape=self._shape, board_cutouts=self._cutouts,
                        settings=self.settings)
```

`place()`'s `radius: float = 3.0, step: float = 0.2` become
`radius: float | None = None, step: float | None = None`, resolved at the top of
the body:

```python
        radius = self.settings.place_radius if radius is None else radius
        step = self.settings.place_step if step is None else step
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_settings_wiring.py tests/test_occupancy.py tests/test_placer.py tests/test_pockets.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/placemat/occupancy.py src/placemat/placer.py src/placemat/layout.py tests/test_settings_wiring.py
git commit -m "[place]: the search's constants come from the settings"
```

---

## Task 7: [copper] and [label] reach the verbs

**Files:**
- Modify: `src/placemat/layout.py` (`track`, `pair`, `pour`, `plane`, `finger`, `label`), `src/placemat/copper.py:206,259`
- Test: `tests/test_settings_wiring.py`

**Interfaces:**
- Consumes: `Board.settings` from Task 6.
- Produces: `copper.resolve_bridges(entries, fixed_tracks, via_drill, via_size, bridge_half=1.1)`; every listed verb's numeric default is `None` and resolves from `self.settings`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_settings_wiring.py
from placemat.copper import Pour, Track, Zone
from placemat.values import CopperLayer, Net


def _copper_board(**kw):
    g = board_geometry([footprint("U1", 10, 10, w=4, h=2, inst="u1", nets=("A", "GND")),
                        footprint("R1", 30, 10, w=2, h=1, inst="r1", nets=("GND", "C"))],
                       width=60, height=60)
    b = Board(g, edge_margin=1.0, settings=Settings(**kw))
    b.size(width=60, height=60)
    return b


def test_the_plane_inset_comes_from_the_settings():
    wide = _copper_board(copper_plane_inset=5.0)
    wide.plane(Net("GND"), layers=(CopperLayer.F,))
    (z,) = [op for op in wide.resolve().copper if isinstance(op, Zone)]
    assert min(x for x, _ in z.points) == 5.0


def test_an_explicit_argument_still_beats_the_setting():
    b = _copper_board(copper_plane_inset=5.0)
    b.plane(Net("GND"), layers=(CopperLayer.F,), inset=1.0)
    (z,) = [op for op in b.resolve().copper if isinstance(op, Zone)]
    assert min(x for x, _ in z.points) == 1.0


def test_the_pour_stroke_comes_from_the_settings():
    b = _copper_board(copper_pour_stroke=0.9)
    b.pour(Net("GND"), [Location(5, 5), Location(15, 5), Location(15, 15), Location(5, 15)],
           layer=CopperLayer.F)
    (p,) = [op for op in b.resolve().copper if isinstance(op, Pour)]
    assert p.stroke == 0.9


def test_the_track_chamfer_comes_from_the_settings():
    """A right angle is cut back `copper.chamfer` along both legs into two 45s,
    so a bigger chamfer means the corner point moves further from the corner."""
    sharp = _copper_board(copper_chamfer=0.0)
    sharp.track(Net("GND"), [Location(10, 10), Location(10, 20), Location(20, 20)],
                layer=CopperLayer.F)
    blunt = _copper_board(copper_chamfer=2.0)
    blunt.track(Net("GND"), [Location(10, 10), Location(10, 20), Location(20, 20)],
                layer=CopperLayer.F)
    n_sharp = len([op for op in sharp.resolve().copper if isinstance(op, Track)])
    n_blunt = len([op for op in blunt.resolve().copper if isinstance(op, Track)])
    assert n_blunt > n_sharp


def test_the_label_size_comes_from_the_settings():
    from placemat.copper import Text
    b = _copper_board(label_size=2.5)
    b.place(Part("u1"), at=Location(20, 20))
    b.label(Part("u1"), "MCU")
    (t,) = [op for op in b.resolve().copper if isinstance(op, Text)]
    assert t.size == 2.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_settings_wiring.py -x -q -k "plane_inset or pour_stroke or chamfer or label_size"`
Expected: FAIL - the settings are ignored and the built-in defaults are used

- [ ] **Step 3: Write minimal implementation**

In `layout.py`, change each signature's numeric default to `None` and resolve at
the top of the method body. The full set:

```python
    def track(self, net, points, *, layer, width=None, chamfer: float | None = None, ...):
        chamfer = self.settings.copper_chamfer if chamfer is None else chamfer

    def pair(self, net_p, net_n, path, *, layer, width=None, gap=None,
             chamfer: float | None = None, via_step: float | None = None, ...):
        chamfer = self.settings.copper_pair_chamfer if chamfer is None else chamfer
        via_step = self.settings.copper_pair_via_step if via_step is None else via_step

    def pour(self, net, points, *, layer, stroke: float | None = None, ...):
        stroke = self.settings.copper_pour_stroke if stroke is None else stroke

    def plane(self, net, layers, *, outline=None, inset: float | None = None, chamfer=None,
              clearance: float | None = None, min_thickness: float | None = None, ...):
        inset = self.settings.copper_plane_inset if inset is None else inset
        clearance = self.settings.copper_plane_clearance if clearance is None else clearance
        min_thickness = self.settings.copper_plane_min_thickness if min_thickness is None else min_thickness

    def finger(self, net, *, layer, from_, to, width, bridge_width: float | None = None, ...):
        bridge_width = self.settings.copper_finger_bridge_width if bridge_width is None else bridge_width

    def label(self, item, text, *, side=Edge.NORTH, gap: float | None = None, align="centre",
              size: float | None = None, thickness: float | None = None, ...):
        gap = self.settings.label_gap if gap is None else gap
        size = self.settings.label_size if size is None else size
        thickness = self.settings.label_thickness if thickness is None else thickness
```

`plane`'s existing `chamfer=None` already means "the board's"; leave it.

In `copper.py`, give `resolve_bridges` the parameter and pass it on:

```python
def resolve_bridges(entries, fixed_tracks, via_drill: float, via_size: float,
                    bridge_half: float = BRIDGE_HALF):
    ...
        ops += bridge_track(t, seen, via_drill, via_size, bridge_half) if seen else [t]
```

and in `layout._plan_copper`:

```python
        ops, notes, findings = resolve_bridges(entries, ctx.fixed_tracks, self.via_drill,
                                               self.via_size, self.settings.copper_bridge_half)
```

Pass `self.settings.copper_bridge_half` to `finger_ops`'s `notch_half` in
`finger`'s `plan(ctx)` as well.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_settings_wiring.py tests/test_copper.py tests/test_labels.py tests/test_bridging.py tests/test_pair.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/placemat/layout.py src/placemat/copper.py tests/test_settings_wiring.py
git commit -m "[copper] and [label]: a verb's default comes from the settings"
```

---

## Task 8: [geometry] through the scoped binding

**Files:**
- Modify: `src/placemat/cutouts.py:21-22,56,93,333`, `src/placemat/kicad/read.py`
- Test: `tests/test_settings_wiring.py`

**Interfaces:**
- Consumes: `settings.active()` from Task 1.
- Produces: `cutouts.flatten_arc(start, arc, sag=None)` reading `active().geometry_arc_sag` when `sag is None`; `SpatialIndex` reading `active().geometry_index_cells`; `read.read_board(path, courtyard_excess_mm=0.10, arc_error_nm=None)`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_settings_wiring.py
from placemat import settings as S
from placemat.cutouts import Arc, flatten_arc


def test_the_arc_sag_bound_for_a_run_decides_how_finely_an_arc_flattens():
    arc = Arc(to=(10.0, 0.0), via=(5.0, 5.0))
    with S.bind(Settings(geometry_arc_sag=0.5)):
        coarse = flatten_arc((0.0, 0.0), arc)
    with S.bind(Settings(geometry_arc_sag=0.001)):
        fine = flatten_arc((0.0, 0.0), arc)
    assert len(fine) > len(coarse)


def test_nothing_bound_flattens_at_the_default():
    arc = Arc(to=(10.0, 0.0), via=(5.0, 5.0))
    assert flatten_arc((0.0, 0.0), arc) == flatten_arc((0.0, 0.0), arc, sag=0.02)


def test_an_explicit_sag_still_beats_the_binding():
    arc = Arc(to=(10.0, 0.0), via=(5.0, 5.0))
    with S.bind(Settings(geometry_arc_sag=0.5)):
        assert flatten_arc((0.0, 0.0), arc, sag=0.001) == flatten_arc((0.0, 0.0), arc, sag=0.001)
        assert len(flatten_arc((0.0, 0.0), arc, sag=0.001)) > len(flatten_arc((0.0, 0.0), arc))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_settings_wiring.py -x -q -k "arc"`
Expected: FAIL - `flatten_arc` ignores the binding and always uses `SAG`

- [ ] **Step 3: Write minimal implementation**

In `cutouts.py`, keep the constants as the documented defaults and read the
binding when the caller said nothing:

```python
SAG = 0.02          # how far a flattened arc may cut the corner off the real one; [geometry] arc_sag
CELLS = 16          # buckets across the longer side: a handful of segments each; [geometry] index_cells


def flatten_arc(start: tuple, arc: Arc, sag: float | None = None) -> list:
    if sag is None:
        from .settings import active
        sag = active().geometry_arc_sag
```

and in `SpatialIndex.__init__`:

```python
        from .settings import active
        self.side = max(max(w, h) / active().geometry_index_cells, 1e-6)
```

The import is inside the function to keep `cutouts` free of an import cycle:
`settings` imports nothing from placemat.

In `kicad/read.py`, thread `arc_error_nm` through this one file:

```python
def read_board(path, courtyard_excess_mm: float = 0.10, arc_error_nm: int | None = None) -> BoardGeometry:
    if arc_error_nm is None:
        from ..settings import active
        arc_error_nm = active().geometry_arc_error_nm
    path = str(Path(path))
    with quiet_stderr():
        board = pcbnew.LoadBoard(path)
    return board_geometry_of(board, path, courtyard_excess_mm, arc_error_nm)
```

`board_geometry_of(board, path, courtyard_excess_mm=0.10, arc_error_nm=CLEAR_ERR_NM)`
passes it to `_footprint(board, fp, excess, cell, err)` -> `_pads(board, fp, err)`
-> `outlines_of(pad, cu[0], err)`, and to `_copper(board, groups_of, err)` ->
`add(..., err)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_settings_wiring.py tests/test_cutouts.py tests/test_outline.py tests/test_round.py tests/test_shaped.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/placemat/cutouts.py src/placemat/kicad/read.py tests/test_settings_wiring.py
git commit -m "[geometry]: the arc tolerances read the bound settings"
```

---

## Task 9: [check], [drc], [route], [timeout], [noise]

**Files:**
- Modify: `src/placemat/checks.py:21-36,386`, `src/placemat/kicad/drc.py`, `src/placemat/kicad/route.py:23,151`, `src/placemat/kicad/quiet.py:15-26`, `src/placemat/kicad/write.py:427-450,540`, `src/placemat/cli.py`, `src/placemat/runner.py`
- Test: `tests/test_settings_wiring.py`, `tests/test_checks.py`

**Interfaces:**
- Consumes: `Settings`, `active()` from Tasks 1-3.
- Produces: `drc.run_drc(pcb, out_json, refill_zones=None, timeout=None, real_kinds=None, outstanding_kinds=None)`; `route.route_board(..., router_dir=None, timeout=None)`; `quiet._is_noise` consults `active().noise_patterns`; `write.render_board(pcb, log, both_faces=False, timeout=None)`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_settings_wiring.py

def test_the_drc_report_classifies_by_the_settings():
    from placemat.kicad.drc import DrcReport
    r = DrcReport(path=None, by_type={"clearance": 2, "silk_overlap": 1},
                  real_kinds=("silk_overlap",), outstanding_kinds=())
    assert r.real == {"silk_overlap": 1}
    assert r.other == {"clearance": 2}


def test_the_default_drc_classification_is_todays():
    from placemat.kicad.drc import DrcReport
    r = DrcReport(path=None, by_type={"clearance": 2, "silk_overlap": 1})
    assert r.real == {"clearance": 2} and r.other == {"silk_overlap": 1}


def test_a_project_pattern_is_added_to_the_built_in_noise_not_instead_of_it():
    from placemat.kicad import quiet
    with S.bind(Settings(noise_patterns=("my own chatter",))):
        assert quiet._is_noise("my own chatter here")
        assert quiet._is_noise("property.h(607): assert ...")
    assert not quiet._is_noise("my own chatter here")
    assert quiet._is_noise("property.h(607): assert ...")


def test_the_router_directory_prefers_the_settings_over_the_environment(monkeypatch):
    from placemat.kicad import route
    monkeypatch.setenv("KRT_DIR", "/from/env")
    assert route.router_dir(Settings()) == "/from/env"
    assert route.router_dir(Settings(route_router_dir="/from/toml")) == "/from/toml"


def test_the_router_directory_falls_back_to_the_built_in(monkeypatch):
    from placemat.kicad import route
    monkeypatch.delenv("KRT_DIR", raising=False)
    assert route.router_dir(Settings()).endswith("KiCadRoutingTools")
```

Add to `tests/test_checks.py`:

```python
def test_the_check_constants_come_from_the_settings():
    """run_checks takes them as arguments; the CLI resolves them from the
    settings, so a project sets them once in placemat.toml."""
    from placemat.settings import Settings
    from placemat import cli
    import argparse
    args = argparse.Namespace(ambient=None, keep_out=None, rise=None, copper_oz=None, limit=[])
    assert cli.overrides_from(args) == {}
    s = Settings(check_ambient_c=42.0)
    assert cli.check_kwargs(s) == {"ambient_c": 42.0, "keep_out_mm": 2.0,
                                   "rise_c": 10.0, "copper_oz": 1.0, "limits": {}}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_settings_wiring.py tests/test_checks.py -x -q -k "drc or noise or router or check_constants"`
Expected: FAIL with `TypeError: DrcReport.__init__() got an unexpected keyword argument 'real_kinds'`

- [ ] **Step 3: Write minimal implementation**

`kicad/drc.py`: replace the module tuples with imports from settings and put
them on the report.

```python
from ..settings import DEFAULT_OUTSTANDING_KINDS, DEFAULT_REAL_KINDS, active

REAL_KINDS = DEFAULT_REAL_KINDS                  # kept: other modules import this name
OUTSTANDING_KINDS = DEFAULT_OUTSTANDING_KINDS


@dataclass
class DrcReport:
    path: Path
    by_type: dict = field(default_factory=dict)
    unconnected: int = 0
    open_nets: Counter = field(default_factory=Counter)
    command: list = field(default_factory=list)
    returncode: int = 0
    stderr_tail: str = ""
    real_kinds: tuple = DEFAULT_REAL_KINDS
    outstanding_kinds: tuple = DEFAULT_OUTSTANDING_KINDS

    @property
    def real(self) -> dict:
        return {k: v for k, v in self.by_type.items() if k in self.real_kinds}

    @property
    def outstanding(self) -> dict:
        return {k: v for k, v in self.by_type.items() if k in self.outstanding_kinds}

    @property
    def other(self) -> dict:
        return {k: v for k, v in self.by_type.items()
                if k not in self.real_kinds and k not in self.outstanding_kinds}
```

and `run_drc` takes the settings' values:

```python
def run_drc(pcb, out_json, refill_zones: bool | None = None, timeout: int | None = None,
            real_kinds=None, outstanding_kinds=None) -> DrcReport:
    cfg = active()
    refill_zones = cfg.drc_refill_zones if refill_zones is None else refill_zones
    timeout = cfg.timeout_drc if timeout is None else timeout
    real_kinds = cfg.drc_real_kinds if real_kinds is None else real_kinds
    outstanding_kinds = cfg.drc_outstanding_kinds if outstanding_kinds is None else outstanding_kinds
    ...
    report = DrcReport(out_json, command=cmd, returncode=proc.returncode,
                       stderr_tail=..., real_kinds=tuple(real_kinds),
                       outstanding_kinds=tuple(outstanding_kinds))
```

`kicad/quiet.py`:

```python
DEFAULT_PATTERNS = tuple(re.compile(p) for p in (
    r"property\.h\(\d+\): assert",
    r"Debug: Adding duplicate image handler",
    r"swig/python detected a memory leak"))
NOISE = DEFAULT_PATTERNS            # kept for anything importing the name


def _is_noise(line: str) -> bool:
    from ..settings import active
    extra = active().noise_patterns
    return any(p.search(line) for p in DEFAULT_PATTERNS) or any(re.search(p, line) for p in extra)
```

`kicad/route.py`:

```python
BUILTIN_ROUTER = os.path.expanduser("~/work/KiCadRoutingTools")


def router_dir(cfg=None) -> str:
    """Where the router lives: the built-in default, then $KRT_DIR (a machine
    fact), then placemat.toml (a project fact), which wins."""
    from ..settings import active
    cfg = active() if cfg is None else cfg
    return cfg.route_router_dir or os.environ.get("KRT_DIR") or BUILTIN_ROUTER
```

and `route_board(..., router_dir: str | None = None, timeout: int | None = None)`
resolving both from `active()` when None. Keep the name `ROUTER_DEFAULT` as an
alias of `BUILTIN_ROUTER` so nothing importing it breaks.

`kicad/write.py`: `render_board(pcb_path, log, both_faces=False, timeout=None)`
resolving `active().timeout_render`, used at both `subprocess.run` sites.

`cli.py`: add

```python
def check_kwargs(s) -> dict:
    return {"ambient_c": s.check_ambient_c, "keep_out_mm": s.check_keep_out_mm,
            "rise_c": s.check_rise_c, "copper_oz": s.check_copper_oz,
            "limits": dict(s.check_limits)}
```

and rewrite `cmd_check` to `load(...)` the settings with `overrides_from(args)`,
`bind` them round the read and the checks, and call
`checks.run_checks(geometry, **check_kwargs(s))`.

`runner.py`: use `cfg.timeout_generate` in `generate`, and let `run_drc`,
`route_board` and `render_board` take their values from the binding.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS except the known pre-existing `tests/test_version.py::test_the_installed_package_reports_that_version_too` failure (stale editable install metadata)

- [ ] **Step 5: Commit**

```bash
git add src/placemat tests
git commit -m "[check], [drc], [route], [timeout] and [noise] come from the settings"
```

---

## Task 10: Documentation, and the Breakout is unchanged without a placemat.toml

**Files:**
- Modify: `skills/placemat/references/api.md`, `skills/placemat/SKILL.md`
- Test: `tests/test_settings_wiring.py`

**Interfaces:**
- Consumes: everything above.
- Produces: no new code interface.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_settings_wiring.py
from tests.conftest import needs_breakout, needs_kicad


@needs_kicad
@needs_breakout
def test_a_board_with_no_placemat_toml_reads_exactly_as_it_did(breakout_pcb, tmp_path):
    """Every default is today's value, so a project with no file behaves as
    it does now. Read the committed Breakout with the defaults bound and with
    nothing bound, and get the same geometry."""
    from placemat.kicad.read import read_board
    from placemat.settings import Settings, bind
    plain = read_board(breakout_pcb)
    with bind(Settings()):
        bound = read_board(breakout_pcb)
    assert [fp.ref for fp in plain.footprints] == [fp.ref for fp in bound.footprints]
    assert [fp.courtyard_box for fp in plain.footprints] == [fp.courtyard_box for fp in bound.footprints]


def test_every_setting_is_documented_in_the_api_reference():
    """A setting nobody can find is a setting nobody uses."""
    from pathlib import Path
    from placemat.settings import Settings, split_key
    doc = Path("skills/placemat/references/api.md").read_text()
    missing = ["%s.%s" % split_key(k) for k in Settings.keys()
               if "%s.%s" % split_key(k) not in doc]
    assert not missing, missing
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_settings_wiring.py -x -q -k "documented"`
Expected: FAIL listing every setting name

- [ ] **Step 3: Write minimal implementation**

Add a Settings section to `skills/placemat/references/api.md`, after Commands:

````markdown
## Settings

`placemat.toml` holds every behavioural constant. It is found by walking up
from the board's directory, and every file on that path contributes: the
NEAREST file wins per key, so a project root sets the house style and one
board overrides one number.

```
built-in default  <  placemat.toml (nearest wins per key)  <  CLI flag
```

An unknown section or key, a wrong type or a value outside its range is an
error naming the file and the key. A setting that quietly did nothing would
read as though it were in force.

`placemat settings [<script-or-dir>] [--json]` prints every resolved value and
the file it came from.

| key | default | what it governs |
|---|---|---|
| `rank.area` | 0.7 | weight on courtyard area when ordering searched items |
| `rank.pins` | 0.3 | weight on pin count when ordering searched items |
| `place.radius` | 3.0 | a search's default radius |
| `place.step` | 0.2 | a search's default step |
| `place.coarse_steps` | 4 | how many steps apart a scored scan's first pass walks |
| `place.coarse_from` | 12 | radius-to-step ratio from which a scan goes coarse first |
| `place.refine_around` | 3 | how many of the best coarse spots get a fine pass |
| `place.block_gap_step` | 0.05 | how finely a block's tightest gap is searched |
| `place.block_gap_reach` | 2.0 | how far a satellite may stand off its pin |
| `place.courtyard_touch` | 0.02 | two courtyards this close are touching, not overlapping |
| `place.conflict_gap` | 1.0 | how far outside a box a conflict can still reach |
| `copper.chamfer` | 1.0 | how far a right angle is cut back into two 45s |
| `copper.pair_chamfer` | 0.5 | the same, for a differential pair |
| `copper.pair_via_step` | 0.4 | how far clear of its partner a pair's lead vias |
| `copper.bridge_half` | 1.1 | half the gap a bridge leaves round a crossed track |
| `copper.finger_bridge_width` | 1.0 | the width of a finger's bridge under a track |
| `copper.plane_inset` | 0.4 | how far a plane is inset from the board edge |
| `copper.plane_clearance` | 0.2 | a zone's pullback from foreign copper |
| `copper.plane_min_thickness` | 0.2 | a zone's minimum filled width |
| `copper.pour_stroke` | 0.2 | a pour's outline stroke |
| `label.size` | 1.0 | silkscreen text height |
| `label.thickness` | 0.15 | silkscreen stroke width |
| `label.gap` | 0.0 | a label's gap from what it names |
| `geometry.arc_sag` | 0.02 | how far a flattened arc may cut the corner off the real one |
| `geometry.index_cells` | 16 | buckets across the longer side of the spatial index |
| `geometry.arc_error_nm` | 5000 | arc approximation error when reading pad outlines |
| `check.ambient_c` | 100.0 | board temperature the junction estimate starts from (`--ambient`) |
| `check.keep_out_mm` | 2.0 | how far sense copper stays from a switch node (`--keep-out`) |
| `check.rise_c` | 10.0 | the rise a current path is sized for (`--rise`) |
| `check.copper_oz` | 1.0 | outer copper weight the widths are sized for (`--copper-oz`) |
| `check.limits` | none | a bound per check, e.g. `"hot-loop" = 20.0` (`--limit`) |
| `drc.real_kinds` | eight classes | which violations mean the board is not done |
| `drc.outstanding_kinds` | three classes | which violations are copper not yet joined |
| `drc.refill_zones` | true | refill zones for the check |
| `route.router_dir` | `$KRT_DIR`, else `~/work/KiCadRoutingTools` | the KiCadRoutingTools checkout |
| `route.quick` | true | one routing round rather than the router's full run |
| `route.iterations` | the router's own | cap on the router's search per net |
| `route.layers` | every copper layer | which layers the router may use |
| `timeout.generate` | 900 | seconds for `pcb layout` |
| `timeout.drc` | 600 | seconds for kicad-cli DRC |
| `timeout.route` | 3600 | seconds for the router |
| `timeout.render` | 300 | seconds for a render |
| `noise.patterns` | none | extra KiCad stderr patterns to suppress, ADDED to the built-ins |

Every verb whose default appears here takes an explicit argument that still
wins: `board.plane(..., inset=1.0)` beats `copper.plane_inset`.
````

Add `placemat settings` to the Commands block in the same file, and a line to
`SKILL.md`: "Before reading a board's numbers, run `placemat settings` - the
values it was laid out with may not be the defaults."

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_settings_wiring.py -q`
Expected: PASS

- [ ] **Step 5: Run the whole suite and commit**

```bash
.venv/bin/python -m pytest -q
git add skills src tests
git commit -m "Document every setting, and prove the defaults are today's values"
```

---

## Acceptance criteria

1. `.venv/bin/python -m pytest -q` passes, except the pre-existing
   `test_the_installed_package_reports_that_version_too` failure caused by
   stale editable-install metadata.
2. `placemat settings` prints every key, its value and its source.
3. A project with no `placemat.toml` produces the same geometry as before.
4. An unknown key, an unknown section, a wrong type and an out-of-range value
   each raise `SettingsError` naming the file and the key.
5. Two runs differing only in a `placemat.toml` value get different run ids.
6. Every `Settings` key appears in `api.md`.
7. `git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"`
   returns nothing for every commit made.
