# Board facts: where each lives, asking for them, fixed against preferred

Status: draft, for approval.

Source: Ben, through the fairing completion session (2026-09-30). Today:
- fab-profile.json holds only `courtyard.excess_mm`;
- the stackup is described only in prose (ARCHITECTURE.md, board_rules.zen);
- placemat.toml holds `[check] copper_oz` and `rise_c`, for outer copper
  only;
- nothing in the skill asks a session to establish any of this.

## What the board already carries

The board's .zen declares a `BoardConfig`, which the generator writes into
the KiCad board's setup. It includes a `Stackup` (stdlib
`board_config.zen`): each copper layer's thickness and role, and each
dielectric's thickness and material. KiCad keeps this in the board file,
and the fab builds from it. placemat already reads the layer roles
(`BoardGeometry.layer_types`) but not the copper weights.

On the fairing core the generated stackup is the stdlib 6-layer default:
- outer copper 0.035 mm (1 oz); inner copper 0.0152 mm (0.5 oz);
- roles: F mixed, In1 power, In2 power, In3 mixed, In4 power, B mixed.

The prose says F signal / In1 GND / In2 signal / In3 3V3 / In4 GND /
B signal, and Ben plans 1 oz inner copper. The board and the prose already
disagree, and nothing reports it.

## 1. Where each fact lives

| Fact | Home | Why |
|---|---|---|
| Layer count, each copper layer's role and weight, dielectrics | the board's .zen `BoardConfig.stackup`; placemat reads it from the generated board | The fab builds from the board file, and the stdlib derives impedance widths from the same stackup. A second copy would drift, as the prose has. |
| Which planes sit on which layers | the layout script's `board.plane()` | Unchanged. KiCad's layer role says signal, power or mixed, not which net. |
| Via types the fab makes, each fixed on, fixed off, or preferred off | fab-profile.json `via` | What the fab and its price allow. |
| Fab minimums (track, clearance, drill, annular ring, via size) | fab-profile.json `min` | What the fab can make. The board's own rules (the .zen `Constraints` and net classes) are the design's choice within them. |
| How a board is judged: temperature rise | placemat.toml `[check] rise_c` | A judgement about this board, not a physical fact. |

`[check] copper_oz` is retired. The current-path check reads each layer's
own copper weight from the board and uses IPC-2221's inner-layer constant
for an inner layer. A placemat.toml that still sets `copper_oz` is refused,
with a note naming the board's weights and the .zen field that sets them.
Two sources for one fact is the overlap to remove.

placemat checks the board's rules against the fab's minimums when a run
starts. A rule or net class below the fab's minimum is a finding of kind
`fab`, naming the rule and both values.

The existing fab-profile keys stay as they are: via default drill and
size, track presets, courtyard.

## 2. Asking for the facts

A new command, `placemat facts <board or script>`, prints each fact from
section 1, its value and where it came from:
- each copper layer's role and weight, from the board;
- the planes, from the script;
- via types with their tier, and the fab minimums, from fab-profile.json;
- the rise, from placemat.toml.

It marks a fact **unconfirmed** when either:
- its file does not set it (no `via` or `min` in fab-profile.json, no
  `rise_c` in placemat.toml); or
- the facts have changed since they were last confirmed.

A layer is also flagged when its KiCad role disagrees with the planes the
script declares on it: a signal layer that carries a `plane()`, or a power
layer that carries none.

Confirmation is a record of the user's decision, not a copy of the facts.
`placemat facts --confirm` writes a digest of the printed facts to
placemat.toml as `[facts] confirmed = "<digest>"`.
- A run whose facts do not match that digest says so on its first line
  ("facts: unconfirmed - placemat facts") and records a finding of kind
  `facts`.
- It still runs, so a module fragment or a study is not blocked.

The skill gets a step before any placement on a board:
- Run `placemat facts`.
- If anything is unconfirmed, ask the user with AskUserQuestion for each
  unconfirmed fact: layer roles and copper weights, via types and their
  tier, fab minimums, rise. Put the answers where section 1 says: the
  stackup in the .zen, the rest in fab-profile.json and placemat.toml.
  Regenerate, then run `placemat facts --confirm`.
- Never proceed on a default, and never write a fact the user did not give.

## 3. Fixed against preferred

Each via type in fab-profile.json takes one of three values:

```json
"via": {"micro": "no", "blind": "if-needed", "buried": "no"}
```

- `"yes"`: fixed on. placemat uses it where a script asks for it, and give
  way may use it (below).
- `"no"`: fixed off. Refused wherever it is asked for, as today.
- `"if-needed"`: preferred off. placemat never draws it. Where an item
  cannot be placed, and this type would have let it place, placemat says so
  and leaves the choice to the user.

The 0.57 keys `allow_micro` / `allow_blind` / `allow_buried` read as
`"yes"` when true and `"no"` when false. A type the file does not name is
`"no"`, and `placemat facts` marks it unconfirmed.

**Where a via type can make the difference.** Today placemat never picks a
via type itself: a span comes from the script (`layers=`) or a fragment.
The usual blocker is a through drop field under a part that wants the far
face. So give way gets a fourth way, after share, move and drop: **shorten**.
- A carried drop of a plane net whose plane lies between its pad's face and
  the far face becomes a via from its face to the nearest layer of that
  plane: F-In1 for a GND drop from the front with GND on In1 and In4.
- The shortened via is copper and a hole on those layers only.
- Its type is whatever that span is: micro for one layer, blind for more.
- It is priced at `score.via_shorten` (default 5, between move and drop).

With the type at `"yes"`, shorten is a real way. With `"if-needed"`, shorten
is judged but never applied:
- A search that finds no legal spot, but would have found one with the
  if-needed type, says so on the step: "protect: no spot; it places with 6
  GND drops as B-In4 blind vias (via.blind is if-needed in
  fab-profile.json)".
- The same sentence is a finding of kind `needs`, so it shows in the run
  summary and in `impact`.
- The spot is still refused. The user decides by setting the type to
  `"yes"`.

A script's `layers=` span of an if-needed type is refused like a `"no"`,
with the reason that the type is preferred off.

Only via types get this now. The value form (`"yes"` / `"no"` /
`"if-needed"`) is the one a later preferred fact would use.

## Verification

- Stackup read:
  - a board with 0.5 oz inner copper judges an inner track's current path
    with the inner constant and 0.5 oz;
  - a placemat.toml with `copper_oz` is refused, naming the board's
    weights.
- Fab minimums: a net class below `min.track_mm` is a `fab` finding.
- `placemat facts`:
  - a board with no fab-profile `via` section is unconfirmed;
  - `--confirm` writes the digest;
  - a changed copper weight makes it unconfirmed again, and the run says
    so;
  - a signal layer carrying a `plane()` is flagged.
- Shorten:
  - with blind `"yes"`, a cell whose GND drop field lies under a far-face
    pad places, its drops written as KiCad blind vias of the right span;
  - with `"if-needed"`, the same cell is refused, with the step note and a
    `needs` finding naming the count, net, span and fab-profile key;
  - with `"no"`, the refusal is as today.
- Migration: `allow_*` keys read as before; the digest parity tests pass.
- Skill: a pressure test of the new step. A session given a board with no
  fab-profile `via` section asks before placing, and does not write a
  default.
