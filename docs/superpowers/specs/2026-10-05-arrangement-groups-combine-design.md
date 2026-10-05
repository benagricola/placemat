# Arrangement groups that combine

Approved direction (2026-10-05): a named group of members takes part in a
module's arrangements as one unit with options of its own, combined with
every other item and group, as a single item's options are. The module run
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

- A group is a unit with one or more options. It contributes its default
  (its members' own `place()`) and each option to the product, as an item
  does.
- Combinations that cannot stand together (two adjacent groups both
  upright) are refused by the module run's proof, as any arrangement is;
  the others are still offered.
- An option refused in every combination it appears in is a finding of its
  own, so the author does not read it out of the refusal list.
- Combinations the author knows are bad may be declared and are then not
  laid out.

## Declaring

```python
board.arrangement("pair",
                  flat=[Alt(Part("c1"), rotation=0), Alt(Part("r1"), at=Beside(Part("c1"), Edge.EAST))],
                  upright=[Alt(Part("c1"), rotation=90), Alt(Part("r1"), at=Beside(Part("c1"), Edge.NORTH))],
                  why="the filter pair lies flat or stands")
board.alternative(Part("r_far"), "turned", rotation=90)
board.exclude("pair.upright", "caps.upright", why="both stand in the one column")
```

- `board.arrangement(name, **options, why="")`: each keyword is an option
  of the group, its value a sequence of `Alt(item, **keywords)`. Option
  names follow `check_name`; `why` is not an option name.
- `board.arrangement(name, *alts, why="")`, the 0.99.15 form, is a group
  with one option. It is kept and now combines like any unit: a module
  written against 0.99.15 runs unchanged, every arrangement it had keeps
  its id (below), and the combinations of its groups with its items are
  added.
- The two forms do not mix in one call.
- A member may be in one group only, and a member of a group may not also
  have its own `board.alternative`. Either is an error where the script
  finishes declaring, naming the member and both declarations. (Two units
  that move the same part would lay two places over it.)
- `board.exclude(*choices, why="")`: every combination that holds all of
  `choices` is not laid out. A choice is `item.option`, `group.option`, or
  a one-option group's name. A choice the module does not declare, an
  exclusion that leaves out every combination holding some option, and an
  exclusion of fewer than two choices are errors where the script finishes
  declaring.

## The arrangements

The units are the items with options and the groups, in the order the
script first declares them. The arrangements are the default, then every
combination of the units (each contributing its default and each option),
in `itertools.product` order over the units with the first declared
changing slowest, less the excluded ones.

Ids:
- an item's option: `item.option`, as now;
- a group's option: `group.option`;
- a one-option group (the 0.99.15 form): the group's name alone, as now;
- a combination: the units' choices in unit order joined by `+`
  (`pair.upright+r_far.turned`, `caps_upright+r_vconn.upright`).

Every 0.99.15 id stays valid with the same meaning, so a lock, an
`arrangements=` or a step note written under 0.99.15 still names the same
arrangement. `known_id` and `all_ids` follow the new order. `choices` is
`{unit: option}` for every unit that takes one, a one-option group
recorded as `{group: group}`.

## Limits

`place.arrangement_options_max` applies to each unit, the group's default
counted as one. `place.arrangements_max` applies to the product after
exclusions: an exclusion is the way to bring a module under the limit
without dropping an option. `arrangement.limit` keeps its facts and adds
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
combination costs a full proof. "Names" adds the group option ids. A
group's options are declared when the members only make sense moving
together; otherwise each member's own `alternative` gives more
combinations for the same declarations.

## Board side

No change in form. A board's `arrangements=`, the lock, freeze, explore and
the studio take the new ids as they take the old. A module must be run
again to offer the new combinations; until then its fragment carries what
0.99.15 wrote.

## Errors

- Mixed positional and keyword options in one `board.arrangement`: a
  `TypeError` at the call.
- A member in two groups, or in a group and with its own alternative: a
  declaration error naming both declarations.
- An exclusion naming an unknown choice, of fewer than two choices, or
  removing every combination of some option: a declaration error.

## Testing

- Two groups and an item: the product, its order and its ids; a one-option
  group's ids as in 0.99.15; every 0.99.15 test of ids unchanged.
- Two adjacent groups whose upright options collide: the combination is
  refused, both options are offered in other combinations, no
  `option_dead`.
- An option that collides in every combination: `option_dead` with its
  refusals.
- An exclusion: the combination is not laid out, `run.json` lists it with
  its why, `arrangement.limit` counts after exclusions.
- The declaration errors above, each.
- A 0.99.15 module (positional groups): every arrangement it had keeps its
  id and its places; the combinations of its groups with its items are
  added.
- Bench: every case `same`; a module with no groups lays out what it did.

## Migration

Under "Changed": groups combine with other items and groups; the
positional form is a one-option group and keeps its ids; a member may not
be in a group and have its own alternative. Under "New": group options,
`board.exclude`, `arrangement.option_dead`. A module re-run offers the new
combinations; a board needs no change.
