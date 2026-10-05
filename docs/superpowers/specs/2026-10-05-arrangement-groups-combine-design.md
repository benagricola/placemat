# Arrangement groups that combine

Approved direction (2026-10-05): a named unit of members takes part in a
module's arrangements as one unit with options of its own, combined with
every other item and unit, as a single item's options are. The module run
finds which combinations are incompatible; an option no combination can use
is reported; the author may declare combinations to skip.

Amends `2026-10-04-module-member-variants-design.md` (released in 0.99.15).

Amended 2026-10-05 after the final review: the positional `board.arrangement` is removed rather than kept as a one-option
unit, and `only=` matches by the choices an arrangement holds.

## Today

`arrangements.enumerate_specs` makes the default, the product of the items'
options, then each group on its own (`arrangements.py:128-148`). A group is
one fixed combination: every member it does not name keeps its `place()`,
and no other item's option is laid with it. A pair that moves together and
a part elsewhere in the module that may turn give `pair` and `r.turned`,
never both at once.

## Goal

- A unit has one or more options. It contributes its default
  (its members' own `place()`) and each option to the product, as an item
  does.
- Combinations that cannot stand together (two adjacent units both
  upright) are refused by the module run's proof, as any arrangement is;
  the others are still offered.
- An option refused in every combination it appears in is a finding of its
  own, so the author does not read it out of the refusal list.
- Combinations the author knows are bad may be declared and are then not
  laid out.

## Declaring

```python
pair = board.unit("pair", Part("c1"), Part("r1"))
board.alternative(pair, "flat",
                  Alt(Part("c1"), rotation=0),
                  Alt(Part("r1"), at=Beside(Part("c1"), Edge.EAST)))
board.alternative(pair, "upright",
                  Alt(Part("c1"), rotation=90, why="the pair stands in the column"),
                  Alt(Part("r1"), at=Beside(Part("c1"), Edge.NORTH)))
board.alternative(Part("r_far"), "turned", rotation=90)
board.exclude("pair.upright", "r_far.turned", why="both stand in the one column")
```

- `board.unit(name, *members)` declares a unit and its
  members (parts the script places with `place()`). The unit's default is
  each member's own `place()`. A unit with no option is an error where
  the script finishes declaring.
- `board.alternative(unit, option, *alts)` adds one option to the
  unit, one call per option, as `board.alternative(item, option,
  **keywords)` does for a single item. Each `Alt(item, **keywords)` names
  a member of the unit, at most once per option; a member the option does
  not name keeps its own `place()` in that option. A unit's alternative
  takes `Alt`s and no keywords of its own (a member's `why=` goes in its
  `Alt`); an item's takes keywords and no `Alt`s. Option names follow
  `check_name`, unique within the unit.
- `board.arrangement(name, *alts)`, the 0.99.15 form, is removed. A call
  raises `TypeError` naming `board.unit` with `board.alternative(unit,
  option, *alts)` as the replacement: a unit with one option does what it
  did, and combines. (Decided 2026-10-05: no board project used it. Kept,
  it would have had to stand alone outside the product to keep its
  0.99.15 meaning, a second way to say what a unit says.)
- A member may be in one unit only, and a member of a unit may not also
  have its own `board.alternative`. A second unit naming a member is an
  error at `board.unit`; an item's own alternative on a unit member is
  an error at whichever call comes second; each names both declarations. (Two units
  that move the same part would lay two places over it.)
- `board.exclude(*choices, why="")`: every combination that holds all of
  `choices` is not laid out. A choice is `item.option` or `unit.option`.
  A choice the module does not declare, a choice twice, two options of
  one unit, and an exclusion of fewer than two choices are errors where
  the script finishes declaring. (An exclusion cannot leave out every
  combination holding an option: it names two units, and each keeps its
  default.)

## The arrangements

The units of the product are the items with options and the units
`board.unit` declares, in the order the script first declares them. The arrangements are the default, then every
combination of the units (each contributing its default and each option),
in `itertools.product` order over the units with the first declared
changing slowest, less the excluded ones.

Ids:
- an item's option: `item.option`, as now;
- a unit's option: `unit.option`;
- a combination: the units' choices in unit order joined by `+`
  (`pair.upright+r_far.turned`).

A module of items' options alone makes the arrangements, ids and order
0.99.15 made. `known_id` follows the new order. `choices` is
`{unit: option}` for every unit that takes one.

## only=

An `only=` entry is `default`, a choice, or choices joined by `+` in unit
order (a full combination id is one such entry). Copper exists in every
arrangement that holds all the choices of some entry; `default` is the
module's own layout alone. So copper on one option is laid in every
combination holding that option, as a 0.99.15 `only=` naming an item's
option was where that option stood alone.

An entry that is not of that form, or names a choice the module does not
declare, is an error where the script finishes declaring; the message
lists the module's choices as ids (`cap.upright`). So is an entry every
arrangement holding which an exclusion leaves out: the copper would exist
in none. Copper fitted round or drawn from other copper with an `only=`
needs each of its entries to hold every choice of one of the other's.

## Limits

`place.arrangement_options_max` applies to each unit, the unit's default
counted as one. `place.arrangements_max` applies to the product after
exclusions: an exclusion is the way to bring a module under the limit
without dropping an option. Its default goes from 8 to 16, since a unit
multiplies the count. `arrangement.limit` keeps its facts and adds
`excluded` (how many combinations the exclusions removed).

## The proof

Unchanged: each arrangement is laid out in full and refused on the
module's own checks, and a refused one is not offered. A combination of
two compatible options is offered even when a third combination holding
one of them is refused.

New finding `arrangement.option_dead` (warning), one per unit option whose
every combination was refused, excluded ones not counted: facts `unit`,
`option`, `refused` (the ids), and for each id its refusal reasons as
`arrangement.refused` gives them. A module with a dead option is not
finished: the option is fixed or dropped.

`run.json`'s `arrangements` record gains `excluded` (the ids not laid out,
each with the exclusion's `why`).

## The skill

"Reading the report" changes: a refused combination is expected where two
options cannot stand together, and needs no action when each option is
offered in some other combination; an `arrangement.option_dead` must be
fixed or dropped. Declaring an exclusion is preferred to letting the run
refuse a combination the author can see is bad, since each refused
combination costs a full proof. "Names" adds the unit option ids. A
unit's options are declared when the members only make sense moving
together; otherwise each member's own `alternative` gives more
combinations for the same declarations.

## Board side

No change in form. A board's `arrangements=`, the lock, freeze, explore and
the studio take the new ids as they take the old. A module must be run
again to offer the new combinations; until then its fragment carries what
0.99.15 wrote.

## Errors

- A unit's alternative given place keywords, or an item's given `Alt`s;
  an `Alt` naming a part outside the unit, or one member twice: a
  `TypeError` or `ValueError` at the call.
- A unit with no option: a declaration error.
- A member in two units, or in a unit and with its own alternative: an
  error at the second call naming both declarations.
- An exclusion naming an unknown choice, a choice twice, two options of
  one unit, or fewer than two choices: a declaration error.
- An `only=` entry naming no choice of the module, or held only by
  excluded combinations: a declaration error.
- `board.arrangement`: a `TypeError` at the call.

## Testing

- Two units and an item: the product, its order and its ids. A module of
  items alone: ids, order, choices, overrides and count as the v0.99.15
  tag's `enumerate_specs` gives them.
- `only=`: an entry naming one choice is laid in every combination
  holding it; `default` in the default alone; an unknown entry lists the
  choices; an entry only excluded combinations hold is an error.
- `board.arrangement` raises `TypeError` naming `board.unit`.
- Two adjacent units whose upright options collide: the combination is
  refused, both options are offered in other combinations, no
  `option_dead`.
- An option that collides in every combination: `option_dead` with its
  refusals.
- An exclusion: the combination is not laid out, `run.json` lists it with
  its why, `arrangement.limit` counts after exclusions.
- The declaration errors above, each.
- A real module with a move declared as a unit's option and with the same
  move as an item's option: the same places, offered state and dead
  options, arrangement by arrangement.
- Bench: every case `same`; a module with no units lays out what it did.

## Migration

Under "New": `board.unit` with options by `board.alternative`,
`board.exclude`, `arrangement.option_dead`. Under "Changed": units
combine with other items and units; a module of items alone makes what
it did; a member may not be in a unit and have its own alternative;
`place.arrangements_max` defaults to 16, up from 8; `only=` matches by
the choices an arrangement holds. Under "Removed": `board.arrangement`,
its replacement, and that a module using it fails at the call. A module
re-run offers the new combinations.

## Build notes

Built 2026-10-05. The bench (`fixtures/bench.py --jobs 2`) is the same in every case on every config (33 cases each). The
full suite (`--full`, 5788 passed, 22 skipped, none failed) passed. A real fixture module with one item's alternative and
one move made a unit's option (one `board.arrangement` then) made, under 0.99.15 and at that build, the same places and
offered state for every arrangement 0.99.15 made.

Amended after the final review (2026-10-05): `board.arrangement` removed, `only=` by membership, the skill check reads
`board.unit`. The bench is the same in every case on every config (33 cases each); the suite without `--full` (5582 passed,
22 skipped) and the arrangement, skill-check, settings-docs and finding-text tests with `--full` (512 passed) passed. A module
of items alone enumerates as the v0.99.15 tag does (a test over every shape of up to four items of up to three options).
