# Arrangement groups that combine

Approved direction (2026-10-05): a named unit of members takes part in a
module's arrangements as one unit with options of its own, combined with
every other item and unit, as a single item's options are. The module run
finds which combinations are incompatible; an option no combination can use
is reported; the author may declare combinations to skip.

Amends `2026-10-04-module-member-variants-design.md` (released in 0.99.15).

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
pair = board.unit("pair", Part("c1"), Part("r1"), why="the filter pair moves as one")
board.alternative(pair, "flat",
                  Alt(Part("c1"), rotation=0),
                  Alt(Part("r1"), at=Beside(Part("c1"), Edge.EAST)))
board.alternative(pair, "upright",
                  Alt(Part("c1"), rotation=90),
                  Alt(Part("r1"), at=Beside(Part("c1"), Edge.NORTH)))
board.alternative(Part("r_far"), "turned", rotation=90)
board.exclude("pair.upright", "caps_upright", why="both stand in the one column")
```

- `board.unit(name, *members, why="")` declares a unit and its
  members (parts the script places with `place()`). The unit's default is
  each member's own `place()`. A unit with no option is an error where
  the script finishes declaring.
- `board.alternative(unit, option, *alts, why="")` adds one option to the
  unit, one call per option, as `board.alternative(item, option,
  **keywords)` does for a single item. Each `Alt(item, **keywords)` names
  a member of the unit, at most once per option; a member the option does
  not name keeps its own `place()` in that option. A unit's alternative
  takes `Alt`s and no place keywords; an item's takes keywords and no
  `Alt`s. Option names follow `check_name`, unique within the unit.
- `board.arrangement(name, *alts, why="")`, the 0.99.15 form, is shorthand
  for a unit of the `Alt`s' items with one option. It is kept and now
  combines like any unit: a module written against 0.99.15 runs unchanged,
  every arrangement it had keeps its id (below), and the combinations of
  its units with its items are added.
- A member may be in one unit only, and a member of a unit may not also
  have its own `board.alternative`. A second unit naming a member is an
  error at `board.unit`; an item's own alternative on a unit member is
  an error at whichever call comes second; each names both declarations. (Two units
  that move the same part would lay two places over it.)
- `board.exclude(*choices, why="")`: every combination that holds all of
  `choices` is not laid out. A choice is `item.option`, `unit.option`, or
  a one-option unit's name. A choice the module does not declare, an
  exclusion that leaves out every combination holding some option, and an
  exclusion of fewer than two choices are errors where the script finishes
  declaring.

## The arrangements

The units of the product are the items with options and the units
`board.unit` declares, in the order the script first declares them. The arrangements are the default, then every
combination of the units (each contributing its default and each option),
in `itertools.product` order over the units with the first declared
changing slowest, less the excluded ones.

Ids:
- an item's option: `item.option`, as now;
- a unit's option: `unit.option`;
- a one-option unit (the 0.99.15 form): the unit's name alone, as now;
- a combination: the units' choices in unit order joined by `+`
  (`pair.upright+r_far.turned`, `caps_upright+r_vconn.upright`).

Every 0.99.15 id stays valid with the same meaning, so a lock, an
`arrangements=` or a step note written under 0.99.15 still names the same
arrangement. `known_id` and `all_ids` follow the new order. `choices` is
`{unit: option}` for every unit that takes one, a one-option unit
recorded as `{unit: unit}`.

## Limits

`place.arrangement_options_max` applies to each unit, the unit's default
counted as one. `place.arrangements_max` applies to the product after
exclusions: an exclusion is the way to bring a module under the limit
without dropping an option. Its default goes from 8 to 16, since a unit
multiplies the count where a 0.99.15 `board.arrangement` added one. `arrangement.limit` keeps its facts and adds
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
- A member in two units, or in a unit and with its own alternative: a
  declaration error naming both declarations.
- An exclusion naming an unknown choice, of fewer than two choices, or
  removing every combination of some option: a declaration error.

## Testing

- Two units and an item: the product, its order and its ids; a one-option
  unit's ids as in 0.99.15; every 0.99.15 test of ids unchanged.
- Two adjacent units whose upright options collide: the combination is
  refused, both options are offered in other combinations, no
  `option_dead`.
- An option that collides in every combination: `option_dead` with its
  refusals.
- An exclusion: the combination is not laid out, `run.json` lists it with
  its why, `arrangement.limit` counts after exclusions.
- The declaration errors above, each.
- A 0.99.15 module (positional units): every arrangement it had keeps its
  id and its places; the combinations of its units with its items are
  added.
- Bench: every case `same`; a module with no units lays out what it did.

## Migration

Under "Changed": units combine with other items and units; the
positional form is a one-option unit and keeps its ids; a member may not
be in a unit and have its own alternative; `place.arrangements_max` defaults
to 16, up from 8. Under "New": `board.unit` with options by `board.alternative`,
`board.exclude`, `arrangement.option_dead`. A module re-run offers the new
combinations; a board needs no change.

## Build notes

Built 2026-10-05. The bench (`fixtures/bench.py --jobs 2`) is the same in every case on every config (33 cases each). The
full suite (`--full`, 5788 passed, 22 skipped, none failed) passed. The usb5v fixture module with a 0.99.15 declaration (one
`board.arrangement`, one item alternative) makes, under 0.99.15 and now, `default`, `c_vcc.turned` and `rt_apart` with the same
places and the same offered state; now it also makes `c_vcc.turned+rt_apart`.
