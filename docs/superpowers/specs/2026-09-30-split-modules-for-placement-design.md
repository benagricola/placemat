# Modules split by placement requirement

Status: draft, for approval.

Source: Ben, through a board's session (2026-09-30).

## The rule

Parts with a close placement requirement belong in one module. A close
requirement is one of:
- a switching loop;
- a bypass capacitor at its pin;
- a Kelvin sense;
- a series part in a tuned run;
- a barrier at a connector.

Parts that can sit elsewhere, joined to the rest only through board-level
nets (a shared bus, status lines, pull-ups, planes), belong in a module of
their own, so each is placed where it belongs.

A module that holds several independent jobs is placed as one rigid cell.
The job with the tightest requirement then drags the others to its spot: a
barrier that must sit at a connector carries a memory and its pull-ups
with it.

## 1. The skill

- **SKILL.md, "A fresh board", step 3 (the model).** A new bullet: a
  cell's parts should share a placement requirement. A module that holds
  jobs joined only through board-level nets is placed as one rigid piece,
  so its tightest job decides where all of them go. Split it in the capture
  before laying out the board. Read the `split` finding (section 2).
- **capture.md, a new section "Modules for placement"**, for a capture that
  defines modules: the rule above; the test in section 2; and that
  splitting changes no net, only which module a part belongs to.

## 2. A finding: a cell of several jobs

At each run, placemat groups each cell's members by the nets local to the
cell:
- A net is **local** when every one of its pads is on the cell's members.
- Plane nets (`board.plane()`) are not local, whatever their pads.
- Two members are in one group when a local net joins them, directly or
  through other members.

A cell with two or more groups of two or more members is a finding of kind
`split`:

"m: its parts form 3 groups joined only by board-level nets: U3, C7, R2;
U5, R4; Q2, R9 (and 4 loose parts: C1, C2, C3, R1). Parts with no close
placement requirement in common may be split into modules of their own."

- A loose part is a member with no local net. A bypass capacitor is one:
  it belongs at its pin, and the reader places it by its pin, not its
  group. So loose parts are listed and do not make a finding on their
  own.
- The finding carries no run-score weight, and it is noted on the cell's
  step.
- `place.split_min_group` (default 2) is the least members a group needs
  to count.

A cell whose members form one group, or one group and loose parts, is not
reported.

## 3. The capture skill

circuit-capture is a separate skill, and the two skills stand alone. The
coordinator tells Ben that the same rule may belong there. placemat's
change does not touch it.

## Verification

- A cell of two independent pairs (U1-R1 on a local net, U2-R2 on another,
  joined only by a plane and a board-level net) is a `split` finding
  naming both groups.
- A cell with one group and two bypass capacitors (loose) is not.
- A plane net shared by every member joins nothing.
- A net with a pad outside the cell joins nothing.
- `place.split_min_group = 3` drops a finding whose groups are pairs.
- The finding has no run-score weight: the run score is unchanged on the
  bench (the bench's modules place with their cells released, so the bench
  tally is "same 32").
