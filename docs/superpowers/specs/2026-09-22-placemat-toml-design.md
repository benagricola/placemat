# placemat.toml: the behavioural constants a project may set

Date: 2026-09-22
Status: design, awaiting approval

Prerequisite for `2026-09-22-placement-rank-design.md`, which needs somewhere to
put the rank weights.

## What exists today

Two config mechanisms, neither able to hold a behavioural setting.

`fab-profile.json` (`project.py:88-108`) is found by walking up from the board
directory and holds what the fabricator can make: via drill and size, courtyard
excess, track-width presets. It takes the first file found, whole. It is the
right home for manufacturing facts and the wrong one for how the placer orders
parts. None of `fairing-instrument`'s boards has one; all three copies live in
`mnb-ecosystem`.

CLI flags with module-constant defaults: `placemat check` exposes `--ambient`,
`--keep-out`, `--rise` and `--copper-oz` over `AMBIENT_C`, `KEEP_OUT_MM`,
`TRACK_RISE_C` and `COPPER_OZ` (`checks.py:21-36`). A flag is not versioned with
the board, so the number a board was judged against is not recoverable from the
repository.

Everything else is a module constant or a signature default, and a project that
wants a different value edits placemat.

## The file

`placemat.toml`, found by walking up from the board directory, the way
`fab-profile.json` is. Unlike `fab-profile.json` it MERGES: every file on the
path from the board directory to the filesystem root contributes, and the
nearest file wins per key. A project root sets the house style and one board
overrides one number without restating the rest.

(`fab_profile` keeps its first-found-whole behaviour for now. Making it merge
too is a separate, compatible change, and is out of scope here.)

### Precedence

    built-in default  <  placemat.toml (nearest file wins per key)  <  CLI flag

Every flag that exists today stays and continues to win. A flag left off falls
to the config value, and a key left out of the config falls to the built-in
default. No flag is removed, and no setting becomes flag-only.

### Validation

An unknown section or key is an ERROR naming the file, the key and the nearest
valid name, not a warning and not silence. A typo that quietly does nothing is
the same defect as the keepout that reaches off the board and is discarded
(`PLACEMAT_GAPS.md`, 2026-09-22): the script reads as though the setting is in
force when it is not. A value of the wrong type, or outside its documented
range, is an error the same way.

### The run id

`run_id` is `hash(script_text, generated_board_bytes, tool_version)`
(`report.py:35`), and `runner.py:124` does `shutil.rmtree(final_dir)` when the
id matches. A setting that changes the board but not the id would make two
different runs collide and destroy the earlier one, `route/` included.

So the resolved settings join the hash, as canonical JSON with sorted keys:

```python
run_id(script_text, board_bytes, tool_version, settings_json)
```

All of them, including the ones that cannot change the board. Hashing a check
constant that changed nothing costs one extra run directory; missing one that
did costs the previous run. The asymmetry decides it.

(Noted, not fixed here: `--keep-going` already changes the written board without
entering the id. It belongs in the hash too, and is left for the rank work,
which is what makes it matter.)

## The settings

Grouped by what they govern. Every one is a value placemat hard-codes today; the
"today" column is where it lives now.

### [rank] - how searched items are ordered

| key | default | today |
|---|---|---|
| `area` | 0.7 | new, from the rank design |
| `pins` | 0.3 | new, from the rank design |

### [place] - the search

| key | default | today |
|---|---|---|
| `radius` | 3.0 | `place(radius=3.0)` |
| `step` | 0.2 | `place(step=0.2)` |
| `coarse_steps` | 4 | `placer.COARSE_STEPS` |
| `coarse_from` | 12 | `placer.COARSE_FROM` |
| `refine_around` | 3 | `placer.REFINE_AROUND` |
| `block_gap_step` | 0.05 | `placer.GAP_STEP` |
| `block_gap_reach` | 2.0 | `placer.GAP_REACH` |
| `courtyard_touch` | 0.02 | `occupancy.TOUCH` |
| `conflict_gap` | 1.0 | `occupancy._GAP` |

### [copper]

| key | default | today |
|---|---|---|
| `chamfer` | 1.0 | `track(chamfer=1.0)` |
| `pair_chamfer` | 0.5 | `pair(chamfer=0.5)` |
| `pair_via_step` | 0.4 | `pair(via_step=0.4)` |
| `bridge_half` | 1.1 | `copper.BRIDGE_HALF` |
| `finger_bridge_width` | 1.0 | `finger(bridge_width=1.0)` |
| `plane_inset` | 0.4 | `plane(inset=0.4)` |
| `plane_clearance` | 0.2 | `plane(clearance=0.2)` |
| `plane_min_thickness` | 0.2 | `plane(min_thickness=0.2)` |
| `pour_stroke` | 0.2 | `pour(stroke=0.2)` |

### [label]

| key | default | today |
|---|---|---|
| `size` | 1.0 | `label(size=1.0)` |
| `thickness` | 0.15 | `label(thickness=0.15)` |
| `gap` | 0.0 | `label(gap=0.0)` |

### [geometry]

| key | default | today |
|---|---|---|
| `arc_sag` | 0.02 | `cutouts.SAG` |
| `index_cells` | 16 | `cutouts.CELLS` |
| `arc_error_nm` | 5000 | `kicad/read.CLEAR_ERR_NM` |

### [check] - keeps its four flags

| key | default | flag |
|---|---|---|
| `ambient_c` | 100.0 | `--ambient` |
| `keep_out_mm` | 2.0 | `--keep-out` |
| `rise_c` | 10.0 | `--rise` |
| `copper_oz` | 1.0 | `--copper-oz` |

`--limit CHECK=VALUE` gains a `[check.limits]` table under the same precedence.

### [drc]

| key | default | today |
|---|---|---|
| `real_kinds` | the eight in `drc.REAL_KINDS` | `drc.py:12` |
| `outstanding_kinds` | the three in `drc.OUTSTANDING_KINDS` | `drc.py:18` |
| `refill_zones` | true | `run_drc(refill_zones=True)` |

Which violation classes count as real is a project decision, and today changing
it means editing placemat. A board that accepts a class states it here, with a
comment, instead.

### [route]

| key | default | today |
|---|---|---|
| `router_dir` | `~/work/KiCadRoutingTools` | `$KRT_DIR`, `route.ROUTER_DEFAULT` |
| `quick` | true | `--route-full` inverts it |
| `iterations` | unset (the router's own) | `--iterations` |
| `layers` | unset (all) | `--layers` on `placemat route` |

`$KRT_DIR` keeps working and sits between the default and the config file:
default < `$KRT_DIR` < `placemat.toml` < `--out`/flags. An environment variable
is a machine fact and the config file is a project fact, so the project wins.

### [timeout] - seconds

| key | default | today |
|---|---|---|
| `generate` | 900 | `runner.py:90` |
| `drc` | 600 | `drc.run_drc` |
| `route` | 3600 | `route.route_board` |
| `render` | 300 | `write.py:445`, `write.py:540` |

### [noise] - KiCad stderr

| key | default | today |
|---|---|---|
| `patterns` | the three in `quiet.NOISE` | `kicad/quiet.py:15` |

A project ADDS to the built-in list rather than replacing it, because the
built-ins are KiCad's own noise and suppressing a project's extra lines should
not un-suppress those. `PLACEMAT_SHOW_KICAD=1` still prints everything.

## What does not move

Three kinds of constant stay hard-coded, because they are not behaviour:

**Grid epsilons.** `values._NM` and `placer._SLACK` (both 1e-5) and
`cutouts.NM` are ten KiCad units - the resolution of the file format. Making
them settable invites a value that writes coordinates KiCad cannot represent.

**Physical constants.** `checks._IPC_K_OUTER` (0.048), `_MIL_PER_OZ` (1.378),
`_MM_PER_MIL` (0.0254). These are IPC-2221 and unit conversions. A project that
disagrees with them has a different standard, not a different setting.

**Structural mappings.** `_EDGE_BEARING`, `_CARDINAL`, `_OUTWARD_ROTATION`,
`_EDGE_DIR`, `_KEEPOUT_FLAGS`, `_HJUST`/`_VJUST`, `_PHYS_LAYERS`,
`_COURTYARD_LAYERS`, `_COPPER_LAYER_NAMES`, `_PREFIX`, `STEP_HEADER`,
`FACES_PREFIX`. These are wiring between placemat and KiCad, or definitions of
what a word means. Changing one does not tune behaviour, it breaks it.

The spec states this list so that "every behavioural constant" has an explicit
boundary rather than being argued case by case later.

## How it reaches the code

```python
@dataclass(frozen=True)
class Settings:
    rank_area: float = 0.7
    rank_pins: float = 0.3
    place_step: float = 0.2
    ...
    sources: dict = field(default_factory=dict, compare=False)   # key -> the file it came from
    def json(self) -> str: ...                                   # canonical, for the run id
```

`settings(start, overrides=None) -> Settings` walks up from the board directory,
merges nearest-wins, applies CLI overrides last, and records per key where the
winning value came from.

`Settings` is threaded, not global: `runner` builds it, `Board.__init__` takes
it, and `Occupancy`, `placer` and `copper` receive the values they need as
arguments. placemat's rule that everything outside `kicad/` is pure Python and
unit-testable without KiCad holds, and a test can construct a `Settings` without
a file.

**Signature defaults become `None`.** A verb whose default now comes from
settings takes `None` and resolves at plan time:

```python
def track(self, net, points, *, layer, width=None, chamfer=None, ...):
    chamfer = self.settings.copper_chamfer if chamfer is None else chamfer
```

This is the bulk of the mechanical work and it changes behaviour for any script
that relied on a signature default while its project sets a different value -
which is the point, and is the churn to expect on the first run.

## placemat settings

```
placemat settings [<script-or-board-dir>] [--json]
```

Prints every resolved setting, its value, and which file it came from (or
`default`), the way the rank's step note prints the numbers behind a decision:

```
rank.area              0.7      default
rank.pins              0.3      default
place.step             0.1      electronics/placemat.toml
copper.chamfer         0.4      electronics/boards/main/placemat.toml
check.ambient_c        85.0     electronics/placemat.toml
drc.real_kinds         [8]      default
```

Without it, "which value was this board actually laid out with" is a question
answered by reading three files and knowing the merge rule.

## Test plan

Without KiCad:

1. no `placemat.toml` anywhere gives the built-in defaults, and `sources` says
   `default` for every key;
2. one file at the project root is picked up from a board directory two levels
   down;
3. two files merge nearest-wins per key, and a key only in the outer file
   survives;
4. a CLI override beats both, and `sources` names it;
5. an unknown section, an unknown key, a wrong type and an out-of-range value
   each raise, naming the file and the key;
6. `$KRT_DIR` beats the default and loses to `placemat.toml`;
7. `[noise].patterns` adds to the built-ins rather than replacing them;
8. two runs whose only difference is a `placemat.toml` value get different run
   ids;
9. `Settings.json()` is stable across dict ordering, so an unchanged project
   gets an unchanged id;
10. a verb's `None` default resolves from settings, and an explicit argument
    still beats the setting.

With KiCad: the Breakout runs unchanged with no `placemat.toml` present, byte
for byte against its current record.

## Documentation

- `api.md` gains a Settings section: the file, the search order, the merge rule,
  the precedence, the table of keys, and `placemat settings`.
- Every verb whose default moved says "default: `[section].key`" rather than a
  literal, so the doc does not go stale against the config.
- `SKILL.md` says to run `placemat settings` before reading a board's numbers.

## Out of scope

- Making `fab_profile` merge, or folding `fab-profile.json` into
  `placemat.toml`. Both are defensible; neither is needed for this, and the fab
  file is consumed by three `mnb-ecosystem` projects.
- Per-board sections inside one file (`[board.Main.copper]`). The walk-up merge
  already gives per-board override with no new syntax.
- A `placemat settings --set` writer. Editing TOML by hand is the point.

## Migration

Nothing breaks without a `placemat.toml`: every default is the value placemat
uses today, so a project with no file behaves exactly as it does now. That is
what test 11 asserts against the Breakout.

The work is in placemat, not in the scripts: threading `Settings` through
`Board`, `Occupancy`, `placer` and `copper`, and turning roughly twenty
signature defaults into `None`.
