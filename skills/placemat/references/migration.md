# Migrating a layout script to placemat 0.6

Read this only if the check in `SKILL.md` matched, or a script fails at import
with `AttributeError: type object 'Priority' has no attribute 'FIXED'`. Nothing here is needed for a script written
against 0.6.

## What changed, in one paragraph

`Priority` used to carry four unrelated facts. It now carries one. Whether a
position is decided is `Freedom`, derived from the place you gave it and never
written by hand. Which searched item goes next is a **rank**, worked out from
the item's courtyard area and pin count. Whether failing to place something
stops the run is `required=`. `Priority` is left with `HIGH`, `DEFAULT` and
`LOW`, which a script sets and nothing else does.

## Find the script's legacy use

```sh
grep -nE "Priority\.(FIXED|EDGE)|priority=Priority\.HIGH|priority=Priority\.LOW" <script>
```

Each hit is one of the four cases below. A script with no hits needs no source
change, but read "What moves without you touching anything" at the end.

## 1. `Priority.FIXED` or `Priority.EDGE` on copper

```python
board.via(GND, Location(12.0, 30.0), priority=Priority.FIXED)
board.track(V48, [pad_a, pad_b], layer=F, priority=Priority.FIXED)
```

**Delete the argument.** When a piece of copper is planned is now derived from
its endpoints: copper whose every endpoint belongs to something nothing will
move - a decided part, a cell already down, or plain coordinates - is planned
before the search and becomes an obstacle to it. Copper naming a searched part
is planned after the search.

```python
board.via(GND, Location(12.0, 30.0))
board.track(V48, [pad_a, pad_b], layer=F)
```

The derivation gives the same answer wherever the endpoints were already
decided, which is every case that used to be legal: `priority=Priority.FIXED`
on copper naming a searched part was refused before, so no script has one.

If the intent was "this track wins at a crossing", that is still a priority and
still spelt the same way, but with a level that exists:
`priority=Priority.HIGH`.

## 2. `Priority.FIXED` or `Priority.EDGE` on a placement

```python
board.place(Part("j1"), at=Location(20, 20), priority=Priority.FIXED)
```

**Delete the argument.** This was already refused at declaration time ("the
declaration decided this position, so ... priority=fixed has nothing to
order"), so a working script cannot contain one. If you find one, the script
was never run.

## 3. `priority=Priority.HIGH` to get a big part down early

```python
board.place(Part("l_vbus"), priority=Priority.HIGH)   # a big inductor that kept getting stranded
```

**Delete the argument and run.** This is the workaround the rank exists to
remove. A large, sparsely connected part now goes down early on its own: the
rank scores courtyard area and pin count, so a 31 mm2 two-pin inductor outranks
a shelf of 0402s whatever their net fan-out.

Read the step line before deciding you still need the override:

```
usbconverter.l_vbus   part   rank 19/220   at (32.01, 18.37) rot 0 face back
```

Keep `priority=Priority.HIGH` only if the rank is demonstrably wrong for that
board, and write the reason beside it. It is now a tier **above** the rank,
not a replacement for it.

## 4. `priority=Priority.HIGH` to make a failure fatal

```python
board.place(Cell("mcu"), priority=Priority.HIGH)   # this MUST be placed
```

**Use `required=True`.**

```python
board.place(Cell("mcu"), required=True, why="the MCU has nowhere else it can go")
```

HIGH used to mean two things at once: go first, and stop the run if there is
nowhere to go. It now means only the first. `required=True` means only the
second, works on a decided placement as well as a searched one, and holds even
under `--keep-going`.

**placemat no longer decides on its own that a failure is fatal.** If a script
relied on the old auto-HIGH stopping a run, nothing stops it now: the item is
left off the board, reported as a finding, and the run carries on. Mark the
items that genuinely cannot be left off.

## What moves without you touching anything

**Every board re-places.** The rank replaces the tier, and link pull drops from
the primary sort key to a tie-break, so the order searched items go down in
changes on every board. Expect a large `impact` diff on the first run. Read the
DRC and crossing numbers, not the diff size.

**Copper at literal coordinates becomes an early obstacle.** A track or via
given plain coordinates is now planned before the search, so a searched part's
pads must clear it. This is the intended behaviour and the most likely source
of new findings on the first run. A part that can no longer find a spot is
telling you the copper was always in its way.

**Every run id changes**, because the tool version moved and the resolved
settings joined the hash. The first run after upgrading has nothing to compare
against; `placemat impact <old> <new>` across the boundary still works.

**A run record reader needs updating.** In `run.json`, a step's `priority` is
now `null` for a decided placement, because it has none:

| was | is |
|---|---|
| `steps[].priority == "fixed"` | `steps[].freedom == "fixed"` |
| `steps[].priority == "edge"` | `steps[].freedom == "edge"` |
| `steps[].priority == "high"` | `steps[].priority == "high"` (unchanged: a script said so) |
| nothing | `steps[].rank`, `steps[].rank_of` on a searched placement |
| nothing | `steps[].freedom` on a copper step: which batch planned it |

**A script that monkeypatched the placer.** `_weigh` and `_CRITICAL_SHARE` are
gone, replaced by `Board._rank` and `placemat.ranking`. A patch against either
name fails loudly rather than silently doing nothing.

## While you are here: placemat.toml

Nothing to migrate - a project with no `placemat.toml` behaves exactly as it
did. But the constants a script used to work around by editing placemat, or by
passing a flag every time, now have a home:

```toml
# electronics/placemat.toml
[place]
step = 0.1              # this board is laid out on a 0.1 grid

[check]
ambient_c = 85.0        # was --ambient 85 on every invocation

[drc]
real_kinds = ["clearance", "shorting_items", "hole_clearance"]
```

`placemat settings` prints every resolved value and the file it came from. The
full table is in `api.md`.
