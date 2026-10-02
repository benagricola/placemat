# An escape starts past a part placed beside its part

Status: built (2026-10-02), as a request from a board's session; the owner's hand
layout is the reference.

Source: a board's session (2026-10-02). Builds on `2026-10-02-fan-lanes-to-targets-design.md`
(turned escapes keep clear) and `2026-10-01-escape-lanes-design.md`. No keyword is added.
The same session reported a handoff pin walled in whose own lane gets out; that fix is
under "Handoff pins" below.

## Problem

A 0.4 mm pitch QFN-56 (track 0.16, clearance 0.16) has a west row of ten pins that fan out
north-west at 45 degrees. A bypass part stands beside the chip at the row's middle (pin
46), turned 135, placed `Beside(chip, Edge.WEST, gap=lane, align=(1, pin 45))`. Pins 43-45
are over it and pins 47-52 under it. In the hand layout the risers of the upper fan end
3.80 to 3.91 mm from the pad centres and those of the lower fan 4.73 to 5.40 mm: the lower
45s start past the bypass.

One `escape(chip, [43 ... 52 but 46], turn=Corner.NW)` over the row lays the lower lanes
through the bypass. An escape is laid out as soon as its part is placed (`_place_escapes`,
called after each item), and the bypass is placed after the chip, so "no nearer than clears
the copper placed when it is laid out" (`lanes.py`, `_near_h`) cannot see it. What works
today is two escapes, the lower one with a typed `depth=`: a coordinate standing in for a
fact the board already holds (the part stands there).

## Options

**Lay the escape out after the firm parts placed relative to its part.** The lanes are
reserved when the parts they must keep clear of are down. No new form: the declaration is
the one that exists, and the order is the script's own relations. Costs: a part placed
between the chip and the lanes does not see the lanes; that part is firm, so nothing yields
to it, and what it would have seen of the lanes is a collision finding, which is now the
lane's blocked finding. Parts placed relative to the escape itself must wait for the lanes,
and the two waits must not meet.

**`escape(..., past=Part(...))`.** Name the part the lanes start beyond. Rejected under
"A new form must earn its place": the relation is already in the script (the part is
placed beside the chip), so a keyword would say it a second time, and a keyword left off
or a part left out would place the lanes through it again. The previous spec withdrew a
`past=` for the same reason (`2026-10-02-fan-lanes-to-targets-design.md`, "Fan lanes to
targets"); what it cost there was a lane whose extent depends on a part not placed yet. Here
the lanes' extent is not changed by waiting, only their start is judged against more copper.

**A typed `depth=`.** The innermost lane's offset, as given. Kept as it is, an escape hatch.

## Design

An escape is laid out when its part is placed and every item in its wait set has been
settled. The wait set of an escape is the firm items (FIXED or EDGE, not riders) that

- need the escape's part (their position is said in terms of it: `Beside` it, a `Pin`
  standing a pad on a point of it, a `Past` over its pads, a row of it), and
- do not depend on the escape: their position names no lane, via or point of it, and
  they need no item that does.

Items that depend on the escape wait for its lanes: a firm item whose position names an
escape, a lane, a lane's point or a lane's via is not ready until that escape is laid out.

Fallbacks, so that nothing is placed later than it was:

- When no firm item is ready and an escape whose part is placed is still waiting (two
  escapes whose wait sets hold items that depend on each other's), the waiting escapes are
  laid out, as they were laid before, and placement goes on.
- When the firm phase ends, every escape not laid out is laid out, before the copper that
  is planned from the firm items and before any searched item. A searched part is placed
  after the lanes, as before; the parts that ride it are committed with it, and the lanes
  are laid after them, as before.

The lanes are judged as they always were (`_near_h`: clear of the row's pads, then of the
placed copper, within `place.escape_via_reach`); they now see more placed copper.

Handoff pins. `escapes.path_out(..., exact=True)` judged a pin's way out on a grid of
cells (`place.escape_cell`) flooded in four directions from the pad and its own copper.
Lanes of a turned escape are laid at the least pitch (0.4525 mm across x - y for a 0.32 mm
step), so the way out between neighbours has no room to spare: a cell grid cannot follow a
45 through a corridor that is exactly a track and two clearances wide, and a pin whose lane
could be carried on was reported walled. The search adds octilinear walks from where the
pin's own copper can be carried on (each end of its tracks, and the pad's centre) on a
lattice of `place.escape_cell` steps through that point, moving at 0, 45 and 90 degrees,
and a gap short of the clearance by under a nanometre is a tie, as `occupancy` judges one.
A pad with no copper of its own that stands in a corridor with no room to spare off its
own axis is still judged on the grid alone.

No setting is added: the lattice step is `place.escape_cell`, the tie is the occupancy's.

## Verification

Synthetic (`tests/test_escape_past_part.py`, `tests/test_escape_walled.py`): a QFN-56 with
a bypass turned 135 placed `Beside` the chip.

- The lanes of one escape over pins 44, 45, 47, 48, 49 keep the clearance from the
  bypass's pads, and the lower three start further out than without the bypass; the upper
  two are where they were.
- A part placed `Beside(esc, ...)` is placed after the lanes and stands clear of them.
- Two escapes whose wait sets hold each other's dependents are both laid out and everything
  is placed.
- A pad whose lane runs between two neighbours' 45s at exactly the least pitch is not
  walled; one a hair closer is.

Real module (`fixtures/fairing/mcu_fan`, `tests/test_escape_past_part_real.py`,
`tests/test_escape_south_fan_real.py`): the module's current script with one escape over
the west row's pins 43-45, 47 and 49, the bypass beside the chip. kicad-cli DRC has no
clearance, hole or shorting violation, no lane is reported blocked, and the lanes' risers
are within 0.15 mm of the hand layout's (the lower risers 0.11 mm nearer the row). The
south row's fan (pins 5-14, 45s at the least pitch) raises no `escape_walled` finding; a
trial track of the net's width drawn along each reported pin's lane and out, with kicad-cli
DRC on the board, adds no violation.

## Follow-up: `run=` and a track from a pin beside the row

A second report had the same escape over nine pins with `run=` a lane long and four tracks going on from their
lanes. The wait was applied (the bypass was placed when the lanes were laid out), but `_near_h` judged a lane's start over
the copper `run=` leaves it, a stub of one lane, which ends short of the bypass: the lower lanes stood at the row. The
judged length is now at least the row's depth and a track and a clearance (the length the row's own clearance already uses),
whatever `run=` is. The bypass's track from pin 46, declared pad to pad, was planned after the lanes and found them across
its way; the firm tracks declared from a pad of the escape's part that is not one of its pins, between placed pads, are
now planned when the lanes are laid out and stand in the occupancy while they are, then are taken out and planned again
in their turn (`_reserve_ways`).

The report's script aligned the bypass's V3V3 pad with pin 46 (its comment said pin 45). A pad there overlaps pin 47's riser by
0.04 mm, so that lane cannot leave west and is reported blocked; the real-module test
(`tests/test_escape_west_fan_real.py`) runs the script with the pad level with pin 45, as its comment says.
