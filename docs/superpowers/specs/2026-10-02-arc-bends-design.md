# Tangent arcs for a track's corners

Date: 2026-10-02
Status: design
Source: a board's session, 2026-10-02 (a 50 ohm class net between two cells on
different faces is wanted drawn as a curve, not as 45 degree legs)

## Problem

`board.track` draws legs at 0, 45 and 90 degrees and cuts each right angle
into two 45s (`copper.chamfer`). A trace whose impedance matters sees every
corner as a discontinuity, and the usual remedy is a curved corner. There is
no way to ask for one: a script can only lay `Location` waypoints closer
together to fake a curve, which is a coordinate list standing in for a fact
(the corner radius) and writes dozens of tiny segments.

What is wanted: a track whose corners are circular arcs tangent to both legs,
written to KiCad as arc tracks, held in placemat's occupancy as the copper
they are, judged for clearance as KiCad judges them, and measured as arcs.

## Design

### The form

`bend=` takes two more values:

- `Bend.ARC`: the track's legs are planned as now (octilinear, the fewest
  turns, then the shortest), and every corner between two legs is a tangent
  arc instead of a sharp corner or a chamfer.
- `Bend.ARC_FREE`: the legs are the straight lines between the points as
  given, at any angle, and every corner is a tangent arc. The planner does not
  snap a leg to 0/45/90, so `measure --copper` flags those legs as off
  0/45/90, which they are by request.

The arc replaces the chamfer, so `chamfer=` with either is refused, as is a
`Lane` as first point (an escape reserves its lane with its own chamfer).
`bridge=True` with either is refused: a bridge cuts a straight leg and passes
under, and an arc has no such cut. A crossing of another net's track by an
arc track is the finding any crossing is when neither may bridge.

### The radius

The centreline radius R of every arc of a track:

- `radius=` (mm) on the call, as `chamfer=` is a call's own distance: a stated
  design fact (a stackup's bend rule, a datasheet's figure), never one found
  by trial; or
- else `copper.arc_radius_widths` times the track's width, default 4.

A multiple of the width is the rule because what a bend does to a trace
scales with the trace: the usual floor for a curved bend is a few widths, and
a fixed mm radius is wrong for a wide power trace and for a narrow RF one
alike. R must exceed half the width (the inner edge of the copper would turn
inside out); a radius that does not is refused when the track is declared.

### The arc

At a corner of deflection angle `d` (the angle the direction turns through)
the arc is tangent to both legs. It takes `T = R * tan(d / 2)` of each leg.
Its start and end are the tangent points, its middle the point of the arc on
the corner's bisector, so a leg of the path runs: straight, arc, straight,
arc, straight. A leg shorter than the tangent lengths its two ends need
(`T1 + T2 > L`) is a corner where the arc does not fit.

### A corner an arc does not fit

The track is not drawn, and a finding (kind `copper`) names the corner, its
deflection, the radius and its tangent length, and the leg that is too
short (its length, and what its other end takes). It never falls back to a
sharp corner or to a smaller radius. The fixes the finding names: a smaller
`radius=`, waypoints further apart, or `Bend.ARC_FREE` where the octilinear
legs were what made a short leg.

### Copper held as arcs

`Track` gains `mid` (an optional point): a track with a `mid` is the arc from
`start` through `mid` to `end`, as KiCad's arc track is. Its centre, radius
and sweep are the circle through the three points, so what is held is what
KiCad reads. `length` is the length along the arc; a straight track's is the
distance between its ends.

Its polygon is a conservative one: the ribbon between radius R - h and R + h
(h half the width) with a half-disc cap at each end, every vertex of the
outer edge on or outside the true arc and of the inner edge on or inside
it, with chords no further from the arc than `geometry.arc_error_nm` (5 um,
the error a read arc is tessellated with). The polygon is what the occupancy,
the pour fitting and the native index take, so Python and native judge the
same shape and agree. A pad is judged against it at the arc's true
distance to within that 5 um, on the side that over-reports a conflict.

Where a track's two ends were read as the track (a net tie's collision
position, the bridge resolver's crossing), an arc is its chords at the same
error, or for the net tie its chord (KiCad collides the arc itself; the
position of that collision is not ported for an arc).

A conflict on an arc says so: "the arc of its corner (radius R) at (x, y); a
smaller radius= there keeps clear", as a chamfer's 45 does.

### Written, read and measured

Written as `PCB_ARC` (start, mid, end) on the track's layer and net, with the
legs either side as `PCB_TRACK`s starting and ending at the same nanometre
point, so KiCad's connectivity sees one track.

Read back, an arc is a `track` copper item with `GetLength()` for its length
(already so) and its outline as KiCad tessellates it. `measure --copper` lists
it as `arc`, its length along the arc, and does not flag it off 0/45/90.

The preview draws it as an SVG arc.

### Not covered

`board.pair` keeps its 45 chamfers: the two tracks of a pair would need
concentric arcs of R plus and minus half the pitch. The router reads the
board file itself, and its parser expands an `(arc ...)` track into
segments (`py_router/route.py`, "the parser expands one (arc) into many
Segments"), so a written arc is an obstacle to it without change here.

### Settings

| Setting | Default | |
| --- | --- | --- |
| `copper.arc_radius_widths` | 4.0 | an arc corner's radius, as a multiple of the track width |

## Verification

Tests (`tests/test_arc_bends.py`, `tests/test_arc_bends_kicad.py`):

- the arc of a corner: tangent to both legs, its tangent points `R tan(d/2)`
  from the corner, its mid on the bisector, its length `R * d`; a 45 and a 90
  degree corner, both turn directions.
- the radius: the setting times the width, `radius=` over it, a radius not
  above half the width refused, `chamfer=`, `bridge=` and a `Lane` with an
  arc bend refused.
- a corner that does not fit is a finding, nothing is drawn, the finding
  names the leg; two corners on one short leg that each fit alone do not fit
  together.
- the polygon: every vertex of the outer edge at least the outer radius from
  the centre and no more than the error past it; the inner edge's at most
  the inner radius; a point on the centreline is inside.
- clearance at the arc's true distance: a pad placed where it clears the 45s
  of the chamfered corner but not the arc, and one that clears the arc but
  not the chamfer; the gap the finding reports equals the distance computed
  from the circle, to 5 um.
- Python and native give the same conflict and the same gap for the arc
  against a pad (parity).
- `Bend.ARC_FREE` draws the legs between the points at their own angle with
  arcs at the corners.
- the write: a track with two corners is five pieces in KiCad, two of them
  `PCB_ARC`, their ends meeting the legs'; `kicad-cli` DRC reports no
  clearance, unconnected or dangling-track violation; the arcs' length read
  back equals the planned length; the nearby pad that the arc conflicts with
  is a clearance violation in KiCad's DRC, and the one it clears is not.
- `measure --copper` on the written board: arcs are `arc`, not off
  0/45/90, lengths along the arc.
- a real module of `fixtures/fairing/keep_out` with an arc track added to its
  layout script, run end to end with `kicad-cli` DRC.
