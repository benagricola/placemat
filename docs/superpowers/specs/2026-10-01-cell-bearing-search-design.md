# A turn searched about a fixed point

Date: 2026-10-01
Status: design
Source: a board's session, 2026-10-01 ("A cell turned about a fixed point,
its bearing searched")

## Problem

A cell whose member origin is pinned to a point (windings drawn about a
disc centre) is declared `at=Pin(Part("c.member"), point)` with a fixed
`rotation=`. Any bearing round the circle would do, so the turn is a choice
the script makes by hand. The alternatives do not reach it:

- `OnRim()` slides the item round a rim, but only on `board.disc`; a board
  drawn with `board.outline(...)` has no rim to slide on.
- Leaving `rotation=` out tries the four right-angle turns, and only of a
  searched part: a cell keeps its one rotation.
- `rotations=` takes any angles (`rotations=range(0, 360, 5)` works on a
  part searched round a `Near()`), but a place that is a point is decided,
  and a decided item is laid once at its `rotation`; `rotations=` is read
  and ignored.

What is wanted: the bearing searched, continuous or at a step, and scored as
the search scores anything - links, emitter and limit pairs, `board.push`,
the keepouts and other items it must clear. A bearing to avoid ("not near
where the arms join") is said as intent, not as a range of angles.

## Design

**The turns.** `rotations=` (on `place()` and on `Near`) takes, besides a
list of angles:

- a number, the step in degrees: `rotations=5` is 0, 5, 10 ... 355;
- `Turns.ANY`: every `place.bearing_step` degrees (default 5.0), so a
  script need not carry a step.

Both expand when the item is declared. A step at or below zero, or above 360,
is refused.

**A point with turns to search.** A place that is a point - `Location`,
`Centre`, `Pin` (a part's pad, a cell's member pad or a member's origin),
`Origin`, `Mid` - declared with `rotations=` is no longer decided: its
position stays on the point and its turn is searched. It is a searched item
with one freedom, as `OnRim()` is: it waits its turn in the rank, after the
items placed before it.

Each turn in `rotations=` is laid by the declaration (the point lands on its
spot at that turn). A turn is a candidate when the item is legal there,
judged as a decided place is judged: the board edge and keep-in by what the
item is (a round rim and a member drawn as an arc), keepouts, hard-limit
discs, other items' copper and courtyards, with carried vias allowed to give
way. The candidate with the lowest cost wins, the cost being what a search
scores: link lengths and crossings, push values over their limits, escape
lanes, and the cost of a via giving way. A tie goes to the turn nearest the
`rotation=` given (0 if none), then the smaller angle; with no links, pushes
or lanes every legal turn costs the same, so the item stays at its declared
turn where it is legal.

**Barring bearings.** A turn that is not wanted is barred by what stands
there, not by a range of angles: a `board.keepout(shape, name, at=...)` over
the region to avoid refuses every turn that puts a member in it, and an
emitter or limit pair or a `board.push` costs the turns that stand near an
aggressor. No new form.

**Keepouts that follow the cell.** A rule area the cell's module brings is
moved with the cell to the turn taken, as for any placed cell. A keepout
shaped by a member (`board.keepout(Part, ...)`) stays refused for a searched
item, as it is for any: regions are settled with the firm items.

**When no turn is legal** the item is unplaced, with a finding naming the
turns tried and the most common refusals, as a slide round a rim says it.

**What a pivoted item does not do.** Other items cannot be placed relative to
its pads (`Beside`, `Pin`), as for any searched item. The global solve, the
cleanup pass and explore leave it where its point puts it.

**Setting.** `place.bearing_step`, default 5.0 degrees.

## Verification

Pure tests, synthetic boards:

- `rotations=5`, `rotations=Turns.ANY` and `rotations=range(0, 360, 5)` give
  the same turns; `place.bearing_step` changes `Turns.ANY`; a bad step is
  refused;
- a cell pinned by a member's origin with `rotations=` takes the turn that
  lowers its links' cost, and its member stays on the point at that turn;
- with no links it keeps the declared `rotation=`;
- a keepout over the region at one bearing makes the cell take another;
- a `board.push` from a source costs the turns near it: the cell turns away;
- with every turn refused, the item is unplaced with a finding;
- a rule area of the cell's module follows it to the turn it takes;
- an item placed beside the cell rides it to the turn it takes;
- a part pinned by its pad on a point takes the same form;
- a fixed `rotation=` with no `rotations=` is laid as before.

Bench: the corpus declares no `rotations=` on a decided place, so no
placement is expected to change; the tally goes in the commit.

## The keep-in on a cell's members

The same session reported a fixed cell along a round rim refused for its box.
The cell was already judged by its members' boxes; the refusal came from a
member drawn as an arc, whose own box corner passes the rim. For a place the
script decided, a cell whose member boxes fail is now judged by the corners of
its shapes, as a part turned off the axes is. Scans judge boxes, natively and
in Python alike, so no native change.

## Documentation

`api.md` (`rotations=`, `Turns`, `place.bearing_step`, a point with turns to
search), `migration.md` (new; a `rotations=` on a decided place now searches;
the fixed `rotation=` constant becomes the searched bearing).
