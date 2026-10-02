# placemat charter

## Purpose

placemat turns layout intent, declared in a script over a netlist, into a
manufacturable board. It places parts and plans copper by intent, judges
them as KiCad does, and writes a board that can be viewed and built. Every
hand-computed coordinate a script needs is a gap in placemat to close.

## Principles

### Intent, not coordinates

Scripts say where things go by relation: beside, past, along, on a pad's
edge, searched for a free spot. placemat works out the numbers.

- **Why:** a coordinate goes stale silently when anything near it moves,
  and it hides the reason it was chosen. A relation keeps holding as the
  board changes, and states its reason.
- **Breaking it looks like:** a position computed as X + offset; a typed
  `Location` or point in a script; a rotation picked by reading pad
  offsets; placemat building a coordinate-based form to meet a request; a
  missing form worked round instead of specced; a distance standing in for
  a fact the design should hold (a pour's `reach=` where the net's current
  is known). A coordinate is allowed
  only where the user approves that one site; `board.figure` is only for a
  layout given in a cited datasheet figure.

### Judged as KiCad judges

A rule placemat enforces on a board is KiCad's rule, judged on the same
shapes KiCad uses: copper by copper clearance and copper-to-edge, holes by
hole clearance, net ties by KiCad's exclusion. Where placemat adds a rule of
its own, it is named as placemat's, and it does not stand in for a KiCad
rule on different shapes. A user label is a mark, not a function of the
board: it gives way to parts, staying next to its item.

- **Why:** a check stricter or looser than KiCad's either refuses a board
  KiCad accepts, which costs placements for nothing, or passes a board
  KiCad's DRC fails.
- **Breaking it looks like:** a courtyard held to the copper-to-edge
  keep-in; a rule ported without its exemptions; a part refused or moved
  for a user label.

### A project-agnostic tool

placemat serves every board that uses it. Its code, tests, skill, docs,
specs, backlog and commit messages never name a project, board, module,
part, part number or net that uses it, and never carry one project's
facts. Those projects' boards may be used as fixtures and bench cases.

- **Why:** project wording makes the tool read as rules for that project,
  and agents on other projects take a note about one part as a rule about
  that kind of part.
- **Breaking it looks like:** a project's part, net or module name in a
  migration note, a test name or a backlog item; a form shaped round one
  board's case that would not serve another; a rule written as being about
  one component type.

### Tunables are settings

Every scoring weight, threshold, tolerance or step size is a setting with a
documented default, never a literal in code or a value a script must carry.
A change that can move placements runs the bench, with the tally in the
commit message.

- **Why:** a buried number can't be found, tuned or compared across runs,
  and a placement change without a bench tally can't be judged.
- **Breaking it looks like:** a magic number in the planner or a check; a
  keyword default that repeats a setting's value; a placement change
  committed without a bench tally.

### Fitted, never zones

Copper a script shapes is a static polygon fitted to the copper it joins
and kept clear of other nets, never a KiCad zone that refills round copper
laid later. Zones are for planes and ground fills only.

- **Why:** a zone lets later copper cut through the join it was meant to
  make, and the board that is built differs from the one that was planned.
  A fitted polygon is what was planned and checked.
- **Breaking it looks like:** a plane standing in for a pour that joins
  named pads or vias; a pour written as a zone; pull-back, or converting a
  fitted polygon to a zone.

## Decide alone / ask first

The agent decides alone:

- bug fixes, where a released form does the wrong thing: fixed with a
  failing test first;
- new forms and script API changes that clearly fit the purpose and
  principles: specced, then built;
- releases once the full suite passes, followed by notices to the agents
  of projects that use placemat, then the bench;
- the backlog: filing, merging and dropping items as resolved, and
  replying to other projects' requests.

The agent asks the user first:

- any exception to a principle, for each site;
- a breaking change: removing or changing a form so that scripts must
  migrate;
- anything outside this repository: other projects' files, the router's
  upstream (its work stays on local branches; no issues, pull requests or
  pushes), and deleting files on the real disk to free space;
- a new form whose fit with the charter is unclear.

A new form must earn its place: before building one, check that existing
forms cannot already compose what is asked (a track with a `Past`
waypoint, an escape, a relation). A form that only saves a few lines in one
script is declined, with the composition that says it.

## Scope

placemat owns this repository: the Python package, `native/`, the
`skills/placemat` skill, `BACKLOG.md`, and the specs and plans under
`docs/`.

It works with:

- **KiCad.** Upstream for every rule placemat judges by. placemat reads
  KiCad's code and ports its behaviour; it never changes KiCad.
- **The router (KiCadRoutingTools).** placemat drives it; changes to it
  stay on local branches.
- **Projects that use placemat.** Not named here or anywhere in placemat
  (see "A project-agnostic tool"); their boards may be fixtures. Their
  requests are filed in `BACKLOG.md`, which only placemat's own agent
  edits. A release that answers a request is announced to them, naming
  what they should change.
