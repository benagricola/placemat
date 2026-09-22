# A placement rank from size and pin count, and freedom out of Priority

Date: 2026-09-22
Status: design, awaiting approval
Depends on: 2026-09-22-placemat-toml-design.md

## What is wrong today

`_weigh` (`layout.py:2054-2091`) works out a searched item's priority from a
score, and writes the answer into the `Priority` enum:

```python
score = 0.5 * area / top_area + 0.3 * conns / top_conns + 0.2 * n / top_parts
auto  = Priority.HIGH if (score >= 0.5 and share >= _CRITICAL_SHARE) else \
        Priority.LOW  if score <= 0.1 else Priority.DEFAULT
```

`_CRITICAL_SHARE` is 0.02 (`layout.py:34`): a fraction of the whole board's
area. Three things are wrong with this, and all three are measurable on the
`fairing-instrument` modular core board (220 footprints, 51 x 70 mm).

**HIGH is unreachable on a board of small parts.** The board's largest
courtyard is 115.71 mm2 against a board area of about 3570 mm2, so 3.2%; every
block and cell on it falls under 2%. From the board's own run log
(`.placemat/runs/5a141489/script.log`):

```
block inputpower.efuse       block  default  priority default (auto: 96% of the
largest area, 1.6% of the board, 20 connection(s), 3 part(s)); ... UNPLACED
block usbconverter.vbus_conv block  default  priority default (auto: 73% of the
largest area, 1.2% of the board, 30 connection(s), 5 part(s)); ... UNPLACED
```

The block scoring 96% of the largest area on the board was assigned DEFAULT and
was left off the board. "Critical" is being measured as dominance of the whole
board, when what it has to mean on a dense board is contiguity: a part that
needs the largest free rectangle is critical whether or not it is 2% of the
board.

**With HIGH unreachable, every item is DEFAULT, so the tier orders nothing and
`_next_to_place` decides the whole board.** Its key is
`(-priority.rank, -(fit > 0.25), -pull, -area, key)` (`layout.py:2294`). With
priority constant and `fit` under 0.25 for everything, the board is ordered by
`pull`. Counted over the same log:

```
166 of 201 searched steps decided by "next: strongest pull"
 35                        decided by "next: largest"
 76 of those 166 decided on a winning pull of 1 or 2
```

`pull` is `sum(w for ... in _targets(...))` (`layout.py:2285`), and `_targets`
(`layout.py:1468-1486`) appends one entry per (own pad, already-placed foreign
pad) pair on any net that is not a declared plane or a `free_net`, at weight 1
unless a `link()` says otherwise. So pull is net fan-out. It tracks pin count
and bus membership, and not size at all:

```
ref  inst                      mm2   pins  pull  parts pulling harder
U7   gnss.gnss              115.71     18    16   29 of 220   (largest part on the board)
U4   display.j_panel         61.02     12    10   41          (3rd largest)
U37  usbconverter.l_vbus     31.50      2     6   66
U23  logicsupply.l_3v3       20.65      2     2  125          (18th largest)
```

(Final-state pull, with GND and V3V3 as the board's two declared planes.) A
two-pin part on private nets tops out around 6; anything on a shared bus
accumulates one point per placed pad on it, and `logic.mcu` reaches 102. The
median pull across the board's 144 small two-pin parts is 2.0, so for most of
the board the primary sort key is a counter whose winning value is 1 or 2. It
is near-noise, and it outranks area. Area only speaks when the entire remaining
queue has pull 0.

**`fit` is measured wrong.** `free = occ.free_area()` with no argument sums the
free area of BOTH faces (`occupancy.py:301-320`), while the item can only go on
one, so the `fit > 0.25` gate fires at roughly half the rate it reads as.
`_weigh`'s `share` divides by `occ.board_box.area`, the bounding box, so a
disc's share is understated by about 27%.

**And `Priority` is carrying four unrelated facts.** For a placement it holds
whether the declaration decided the position (FIXED, EDGE), how important the
item is among the searched ones (HIGH, DEFAULT, LOW), and - through
`CriticalUnplaced` at `layout.py:1836` - whether failing to place it stops the
run. For copper, FIXED holds whether the intent is planned before the searched
items and becomes an obstacle to them.

None of those first two is a priority. `place()` derives FIXED and EDGE from
`at=` and then refuses to let a script set them (`layout.py:1186-1196`); the
comment at `layout.py:1174-1180` already says so. And copper's FIXED is the same
question one step along: is this position decided before the search runs?
`_copper_intent` (`layout.py:1520-1524`) already computes the answer and uses it
only to raise an error.

## Four facts, four homes

| fact | set by | carried in |
|---|---|---|
| is the position decided before the search runs | derived: from `at=`, or from the endpoints | `Freedom` (new) |
| which searched item goes next | computed; a script may override | `rank`, and `Priority` |
| which of two crossing tracks passes under | the script | `Priority` |
| whether failing to place it stops the run | the script | `required=` |

`Priority` is reduced to HIGH, DEFAULT and LOW, and is only ever script-set.

### Freedom

```python
class Freedom(str, Enum):
    """Whether a position is decided before the search runs. Derived - from
    at= for a placement, from the endpoints for copper. A script never
    writes one."""
    FIXED    = "fixed"      # a point: Location(x, y), Centre(x, y), Pin(k, x, y), Polar(r, a)
    EDGE     = "edge"       # a distance along an edge, a run or a rim
    SEARCHED = "searched"   # anything with a freedom left

    @property
    def decided(self) -> bool:
        return self is not Freedom.SEARCHED
```

Three values, because three is what `_settle` branches on. A one-freedom place
(`OnEdge(edge)` with no `along=`, `Location(30, None)`, `Polar(radius)`,
`OnRim()`) is SEARCHED, which is what `api.md` already says it is: it goes down
in the searched queue. It now gets a rank too, so a large edge connector claims
its stretch before a small test point does.

The words `fixed` and `edge` are kept, so every finding
(`j_usb (fixed): J5 courtyard overlaps ...`), the collision filter in
`place_ranked` (`layout.py:1861`) and the degrees-of-freedom table in `api.md`
read exactly as they do now. Only the type changes.

`PlaceIntent` gains `freedom: Freedom`; `place_ranked` and `PlaceIntent.rank`
ask `obj.freedom.decided` where they asked `obj.priority in (FIXED, EDGE)`.

### Freedom for copper

Copper's `Priority.FIXED` does two jobs, and neither is a priority.

The first is the bridging guarantee, "a FIXED track never passes under". That is
not delivered by the rank at all: `_plan_copper` plans the firm copper as a
separate, earlier batch and passes it to `resolve_bridges` as `fixed_tracks`,
which every later track yields to unconditionally (`copper.py:243-251`). Within
a batch the rank decides; across batches the earlier one always wins. So the
guarantee survives untouched when FIXED leaves `Priority`.

The second is "planned before the searched items, becomes an obstacle to them",
and that is the same question `Freedom` answers for a placement. It is fully
derivable, so it is derived:

```python
searched = {refdes every searched placement will move}
for c in self._copper:
    c.freedom = Freedom.SEARCHED if (c.owners & searched) else Freedom.FIXED
```

A copper intent is FIXED when every `PadRef` and `CellPadRef` it names belongs
to an item that is not searched, and when it names none at all (literal
coordinates are decided by definition). Otherwise it is SEARCHED.
`Freedom.EDGE` never arises for copper, the way `Priority.LOW` never arises for
a decided placement.

This is derived in `resolve()`, not in `_copper_intent`. Today's check runs at
declaration time, where `_is_searched` iterates only the placements declared so
far, so copper declared before its part's `place()` is silently judged against
an incomplete list. Deriving once every declaration is in removes that.

Two things fall out. `priority=Priority.FIXED` on a copper verb is gone, and
with it the error "FIXED copper may not reference a searched part" - the state
it guarded against is now unrepresentable. And `board.via(net, Location(x, y))`
becomes an early obstacle by itself, which is the `reserve_via` workaround
recorded in `PLACEMAT_GAPS.md` (2026-09-20, "what the main board's script had to
work round"), with nothing to remember.

`CopperIntent.rank` reads `RANK_FIXED_COPPER if self.freedom.decided else
RANK_COPPER`.

### The rank

`_weigh` stops writing `Priority` and computes a static rank over the searched
items, once, before anything is placed. A rank says what a part is; it does not
move as the board fills.

```
score = rank.area * z(ln courtyard_area) + rank.pins * z(ln pin_count)
```

standardised over this board's own searched items. The two weights are
`[rank] area` and `[rank] pins` in `placemat.toml`, defaulting to 0.7 and 0.3;
see `2026-09-22-placemat-toml-design.md`, which this design depends on. The rank
is the position in descending score order; ties keep the same rank.

Log space because the dynamic range is large: on the core board area runs 0.72
to 115.71 mm2 and pins 1 to 57. Z-scores because standardising each dimension
before weighting is what makes 0.7/0.3 deliver 70/30 rather than whatever the
accidental spreads give, and because it is robust: adding one very large
connector does not compress everything else the way dividing by the maximum
does.

The weighting reproduces the four bands without a boundary between them: large
and many pins outranks large and few pins, which outranks small and many pins,
which outranks small and few pins. No percentage of the board appears anywhere,
and `_CRITICAL_SHARE` is deleted.

**Area** is the courtyard box, which is what competes for space:
`fp.courtyard_box.area` for a part, `CellGeom.courtyard_box.area` for a cell
(the envelope the placer has to fit), and the sum of member courtyards for a
block, since a block has no single box until it is laid out at a candidate.

**Pins** is the count of distinct non-empty pad numbers on the footprint (summed
over members for a cell or block), floored at 1. This is the datasheet's pin
count rather than the pad count, and it gets three real cases right for free:
the Keystone 1285's two legs both numbered `1` read as one pin, the 1287's
numbered `1` and `2` read as two, and the TPS16630's four unnamed netless
through-hole pads read as none.

**Connection count leaves the score.** It measured connectivity, and
connectivity is what `pull` is for. A rank says what a part is; pull says where
it goes.

### Ordering

`_next_to_place` sorts by:

```
(-script_tier, -score, -pull, -area, key)
```

`script_tier` is `Priority.rank`, which becomes `{high: 2, default: 1, low: 0}`
now that FIXED and EDGE have left the enum. An item whose priority the script
did not set is DEFAULT, so `priority=Priority.HIGH` still means "before the
rest" and LOW still means "after the rest", and everything else is ordered by
the rank alone.

The rank score is primary. `pull` demotes to a tie-break, which is the right job
for it: the core board's 144 small two-pin parts score identically on area and
pins, tie exactly, and pull then decides among them. That restores the seeding
behaviour precisely where it belongs and nowhere else.

The `fit > 0.25` gate goes. It was trying to say "this needs a big piece of the
board, place it now", which the rank now says properly, and it was measured
against both faces.

`free_area()`'s both-faces default is left alone; nothing else calls it without
a face, and it is used for the run's `free_area_mm2` metric where summing both
faces is what is wanted.

### required=

```python
board.place(item, required=True, why="the MCU has nowhere else it can go")
```

Independent of ordering and of freedom:

- a SEARCHED item that is `required` and finds no place raises
  `CriticalUnplaced`, which is what auto-HIGH does today;
- a decided item (FIXED or EDGE) that is `required` and collides stops the run
  **even under `--keep-going`**;
- nothing else stops a run by itself.

`CriticalUnplaced` keeps its report (envelope, reason, the biggest free
rectangles on the face) and keeps writing the board as it stood.

This is the behaviour change with the widest reach: today an item placemat
decided was HIGH stops the run on its own. After this, placemat never decides
that failure is fatal - the script does.

## What it says

Step lines. The `priority` column becomes a `place` column, holding the freedom
for a decided item and the rank for a searched one:

```
item                         kind   place       result
gnss.gnss                    part   fixed       at (26.10, 6.20) rot 0 face back
display.j_panel              part   fixed       at (26.10, 22.20) rot 0 face front
inputpower.efuse             block  rank 5/64   at (...)  49.0 mm2 (7th of 64), 21 pins (5th)
usbconverter.l_vbus          part   rank 19/64  at (...)  31.5 mm2 (12th), 2 pins (41st)
display.r_term_dc            part   rank 61/64  at (...)  0.6 mm2 (58th), 2 pins (41st)
```

Each searched step names its two measurements and where each sits among the
searched items. No threshold is quoted, because there is none. A script
override reads `rank 61/64 (script: high)`, and `required` appends `, required`.

`run.json` steps:

```json
{"item": "j_usb",     "kind": "part",   "freedom": "fixed",    "priority": null,      "rank": null}
{"item": "logic.mcu", "kind": "part",   "freedom": "searched", "priority": "default", "rank": 1, "rank_of": 64}
{"item": "track V48", "kind": "copper", "freedom": "fixed",    "priority": "default"}
{"item": "track SDA", "kind": "copper", "freedom": "searched", "priority": "low"}
```

A decided placement records `priority: null`, because it has none. Copper
records both: its freedom says which batch planned it, its priority says who it
yields to at a crossing. `report.py` and `impact()` do not read `priority`, so
the impact output is unaffected.

## Errors

- `priority=` on a decided position: unchanged - "the declaration decided this
  position, so the item goes down before anything searched and priority=%s has
  nothing to order".
- `Priority.FIXED` and `Priority.EDGE` no longer exist, so a script naming one
  fails at import with `AttributeError`. `place()` and the copper verbs catch
  the likely intents and say what to use instead: `required=True` for "this must
  be placed", and nothing at all for copper, because it is derived.
- "FIXED copper may not reference a searched part" is deleted. The state it
  guarded against cannot be expressed.

## Test plan

Unit, without KiCad, on synthetic footprints:

1. the four bands order correctly: large+many > large+few > small+many >
   small+few;
2. pin count is distinct non-empty pad numbers - the 1285 (two pads both `1`),
   the 1287 (`1` and `2`) and four unnamed netless pads;
3. identical passives tie exactly on score, and pull decides between them;
4. the score is invariant to a unit change (mm2 against a scaled copy) and is
   not collapsed by one large outlier being added to the board;
5. a cell ranks on its courtyard box, a block on the sum of its members;
6. `required=True` on a searched item with no place raises `CriticalUnplaced`;
7. `required=True` on a colliding FIXED item raises under `keep_going=True`;
8. a searched `OnEdge(edge)` item gets a rank, and a larger one settles first;
9. `freedom` drives `place_ranked`: the existing FIXED/EDGE ordering tests pass
   unchanged;
10. a step records `freedom`, and `priority` is null for a decided placement.

Copper freedom:

11. a track between two pads of FIXED parts derives `Freedom.FIXED`; one naming
    a searched part derives `Freedom.SEARCHED`; one with only literal
    coordinates derives `Freedom.FIXED`;
12. copper declared BEFORE its part's `place()` still derives SEARCHED - the
    ordering bug in today's declaration-time check;
13. a decided track is planned before the searched placements and a searched
    part's pad is refused for landing within clearance of it;
14. a later track crossing an earlier-batch track bridges under it, and one
    that may not bridge is a finding naming it - the existing bridging tests
    pass with `priority=Priority.FIXED` replaced by decided endpoints.

Against the real geometry (skipped without the board): on the core board's
`.kicad_pcb`, `inputpower.efuse` and `usbconverter.vbus_conv` rank in the top
ten. Those are the two blocks that went DEFAULT and UNPLACED.

## Documentation

- `api.md`: the degrees-of-freedom table gains a sentence that a searched item's
  place in the queue is a rank from courtyard area and pin count, and that a
  script's `priority=` is a tier above it. The paragraph ending "HIGH also needs
  a real share of the board" is removed. `required=` is documented on `place()`.
- `api.md`, copper section: "All take `priority=`. `Priority.FIXED` copper is
  planned before everything searched parts and becomes an obstacle to them, and
  may not reference a searched part" becomes a statement that copper naming only
  decided endpoints is planned first and becomes an obstacle, that this is
  derived, and that `priority=` decides only who passes under at a crossing.
- `SKILL.md`: wherever it tells an agent to reach for `priority=Priority.HIGH`
  to get a big part down early, say that the rank does this and that
  `priority=` is for when the rank is wrong. Remove any instruction to mark
  copper FIXED.

## Out of scope

- Scoring against the largest free rectangle on the item's own face rather than
  against the board. It is the better idea for "critical" and it is where this
  should probably end up, but it makes the rank depend on board state, which
  makes it non-static and unstable between steps. Land the static rank first and
  let the next board's numbers argue for it.
- Rounding the score to a resolution so that near-ties fall through to pull. A
  0603 currently outranks an 0402 even when the 0402 has more pull. Harmless,
  and it would be a third weight to choose. Add it, as `[rank] resolution`, only
  if the passive tail places badly.
- An override for "decided, but plan it late". There is no known case: a
  courtyard over a track is already legal (`Occupancy._conflict` returns None
  for courtyard against copper), so planning decided copper early only costs a
  searched part's PADS their clearance, which is what is wanted. Add one if a
  board needs it.
- Separation scoring, and anything else from PLAN.md item 7.

## Migration

Every existing script re-places. Specifically:

- `tests/test_priority.py` is rewritten around the rank.
- `tests/test_critical.py` moves from `priority=Priority.HIGH` to `required=True`.
- 13 test files reference `Priority`; the 39 `Priority.FIXED` and 22
  `Priority.EDGE` uses become `Freedom`, and 16 assertions on the `auto:` /
  `would be` / `(script` note strings are re-read.
- `test_runner_breakout.py` and the Breakout end-to-end expectations are
  re-measured.
- In `fairing-instrument`, all 32 `Priority.FIXED` uses are copper
  (12 `board.track`, 14 `board.via`, 6 continuation lines) and none are
  placements: `priority=Priority.FIXED` is deleted from each, and the
  derivation gives the same answer wherever the endpoints were already decided.
  The four `priority=Priority.HIGH` placement overrides in `Core_layout.py`
  come out too - they exist to work around exactly this.
- `mnb-ecosystem` uses `Priority.HIGH` three times and no `Priority.FIXED`, so
  the Breakout needs only its re-measurement.

A track whose endpoints are literal coordinates changes batch: it is now an
early obstacle where it used to be planned last. Searched parts' pads must clear
it. This is the intended behaviour and the most likely source of new findings on
the first run of an existing script.
