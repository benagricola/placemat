# Board facts: where each lives, asking for them, fixed against preferred

Status: draft, for approval.

Source: Ben, through the fairing completion session and then directly
(2026-09-30). Today:
- fab-profile.json holds only `courtyard.excess_mm`;
- the stackup is described only in prose (ARCHITECTURE.md, board_rules.zen);
- placemat.toml holds `[check] copper_oz` and `rise_c`, and `[route] layers`
  and `diff_pairs`;
- nothing in the skill asks a session to establish any of this.

## The rule

Each kind of fact has one home.

| Home | Holds | Examples |
|---|---|---|
| The board's .zen (`BoardConfig`) | Facts about the board | Stackup: layer count; each copper layer's role and weight; dielectrics. Net classes, including which nets form a differential pair. Design rules. |
| The layout script | What the layout intends | Placement, copper, planes (`board.plane()`) |
| fab-profile.json | What the fab can make, and what its price allows | Via types, fixed or preferred; fab minimums; via and track presets; courtyard excess |
| placemat.toml | Tuning placemat itself | Search, scoring, cleanup, DRC grading, router tuning (`route.islands`, escalation), the rise the current-path check judges by |

placemat.toml holds no fact about the board. A board fact in it is refused
with a note naming the .zen field that holds it. Its keys for board facts
are retired:
- `[check] copper_oz`;
- `[route] layers`;
- `[route] diff_pairs`.

## What the board already carries

The .zen's `BoardConfig` has a `Stackup` (stdlib `board_config.zen`). Each
`CopperLayer` has a thickness and a role (`signal`, `mixed`, `power`,
`ground`); each `DielectricLayer` has a thickness and a material. The
generator writes it into the KiCad board's setup, and the fab builds from
that file.

Each `NetClass` may list its `nets` (names or KiCad wildcard patterns), and
a pair class sets `diff_pair_width` and `diff_pair_gap`. KiCad has no
`ground` layer type: the generator writes `ground` as `power`.

placemat reads the layer types today (`BoardGeometry.layer_types`). It does
not read the copper weights or use the pair classes.

On the fairing core, board_rules.zen declares no stackup, so the board
carries the stdlib 6-layer default:
- copper: F mixed 1 oz; In1 ground, In2 power, In3 mixed and In4 ground,
  each 0.5 oz (0.0152 mm); B mixed 1 oz;
- this does not match the prose: signal / GND / signal / 3V3 / GND /
  signal, with 1 oz inner copper planned.

Its `90Ohm Diff` class lists no nets. So the core's placemat.toml names
the route layers and the pairs by hand.

## 1. placemat reads the board's facts

- **Copper weight.** Each copper layer's thickness is read from the board's
  stackup (`BoardGeometry.copper_mm`, per layer). The current-path check
  judges each piece of copper by its own layer's weight. For an inner layer
  it uses IPC-2221's inner-layer constant (k = 0.024, against 0.048 outer).
  Today it judges every layer as outer copper of `check.copper_oz`.
- **Route layers.** The route step routes on the layers whose role is
  `signal` or `mixed`, with F.Cu and B.Cu always among them. This replaces
  today's default, which leaves out an inner layer that a board-wide plane
  fills. `placemat route --layers` still overrides for one run.
- **Differential pairs.** The nets of a class that sets `diff_pair_width`
  and `diff_pair_gap` are pairs.
  - When the class has exactly two nets, they are one pair whatever they
    are called.
  - When it has more, they pair by `pairs.pair_key`, the router's own
    naming rule.
  - The Default class never makes pairs.
  - Placement (pair partners), scoring and the route step all read these
    pairs.
  - A board whose .zen names no pair class has no pairs. Today every net
    named like a pair is routed as one (`route.diff_pairs` defaults to
    `"*"`).

## 2. Fab capability in fab-profile.json

```json
{
  "via": {"micro": "no", "blind": "if-needed", "buried": "no",
          "default_drill_mm": 0.3, "default_size_mm": 0.6},
  "min": {"track_mm": 0.09, "clearance_mm": 0.09, "drill_mm": 0.15,
          "annular_mm": 0.075, "via_size_mm": 0.25},
  "courtyard": {"excess_mm": 0.1}
}
```

The values above show the form. A board's values come from its fab, and
the session asks for them (section 4).

placemat checks the board's design rules and net classes against `min`
when a run starts. A rule below the fab's minimum is a finding of kind
`fab`, naming the rule and both values.

## 3. Fixed against preferred

Each via type takes one of three values:
- `"yes"`: fixed on. placemat uses it where a script asks for it, and give
  way may use it.
- `"no"`: fixed off. Refused wherever it is asked for, as today.
- `"if-needed"`: preferred off. placemat never draws it. Where an item
  cannot be placed, and this type would have let it place, placemat says so
  and leaves the choice to the user.

The 0.57 keys `allow_micro` / `allow_blind` / `allow_buried` read as
`"yes"` when true and `"no"` when false. A type the file does not name is
`"no"`, and `placemat facts` marks it unconfirmed.

**Shorten, a fourth way to give way.** Today placemat never picks a via
type itself; a span comes from the script (`layers=`) or a fragment. The
usual blocker is a through drop field under a part that wants the far face.
So give way gets a fourth way, after share, move and drop:
- A carried drop of a plane net whose plane lies between its pad's face and
  the far face becomes a via from its face to the nearest layer of that
  plane: F-In1 for a GND drop from the front with GND on In1 and In4.
- The shortened via is copper and a hole on those layers only.
- Its type is whatever that span is: micro for one layer, blind for more.
- It is priced at `score.via_shorten` (default 5, between move and drop).

With the type at `"yes"`, shorten is a real way. With `"if-needed"`, it is
judged but never applied:
- A search that finds no legal spot, but would have found one with the
  if-needed type, says so on the step: "protect: no spot; it places with 6
  GND drops as B-In4 blind vias (via.blind is if-needed in
  fab-profile.json)".
- The same sentence is a finding of kind `needs`, in the run summary and in
  `impact`.
- The spot is still refused. The user decides by setting the type to
  `"yes"`.

A script's `layers=` span of an if-needed type is refused like a `"no"`,
with the reason that the type is preferred off.

Only via types get this now. The value form is the one a later preferred
fact would use.

## 4. Asking for the facts

`placemat facts <board or script>` prints each fact, its value and its
home:
- each copper layer's role and weight, from the board;
- the pair classes and their nets;
- the planes, from the script;
- via types with their tier, and the fab minimums;
- the rise.

It marks a fact **unconfirmed** when any of these holds:
- the board has no confirmation record yet: then every fact is
  unconfirmed, so a board carrying the stdlib's default stackup is asked
  about like any other;
- its home does not set it: fab-profile.json has no `via` or `min`;
- the facts have changed since they were last confirmed.

It also flags a layer whose role disagrees with the script's planes: a
`signal` layer that carries a `plane()`, or a `power`/`ground` layer that
carries none.

`placemat facts --confirm` records the user's decision as a digest of the
printed facts, in placemat.toml's `[facts] confirmed`. This is placemat's
own record, not a board fact.
- A run whose facts do not match that digest says so on its first line
  ("facts: unconfirmed - placemat facts") and records a finding of kind
  `facts`.
- It still runs, so a module fragment or a study is not blocked.

## 5. Skill changes

SKILL.md gets two things:
- **Before any placement on a board, establish the facts.**
  - Run `placemat facts`.
  - For each unconfirmed or flagged fact, ask the user with
    AskUserQuestion: layer roles and copper weights, pair nets, via types
    and their tier, fab minimums, rise.
  - Write each answer in its home from the table above: the stackup and
    pairs in the .zen, fab facts in fab-profile.json, the rise in
    placemat.toml.
  - Regenerate, then run `placemat facts --confirm`.
  - Never proceed on a default, and never write a fact the user did not
    give.
- **Where a change goes.** The table from "The rule", with one line each:
  - to change a board fact, edit the .zen;
  - to change what the fab allows, edit fab-profile.json;
  - to tune placement, scoring or the router, edit placemat.toml;
  - to change what the layout does, edit the script.

api.md's settings table loses the three retired keys and gains
`score.via_shorten`. It says in one line that placemat.toml is tuning only.
capture.md's current-path bullet says the check reads copper weight per
layer from the board.

## 6. Migration

A migration.md section for this release says what to change on a board.

**1. Declare the stackup in the .zen.** In board_rules.zen, give
`BoardConfig` a `stackup`, with each copper layer's role and weight, and
the dielectrics from the fab's stackup for the chosen part number. The
fairing core's, from its prose, with 1 oz inner copper:

```python
load("@stdlib/board_config.zen", "BoardConfig", "CopperLayer", "DielectricLayer",
     "Material", "Stackup", ...)

STACKUP = Stackup(
    thickness = 1.6,
    materials = [...],          # the fab's prepreg and core, as the stdlib's BASE_6L_STACKUP lists them
    layers = [
        CopperLayer(thickness = 0.035, role = "signal"),   # F.Cu
        DielectricLayer(thickness = ..., material = "3313", form = "prepreg"),
        CopperLayer(thickness = 0.035, role = "ground"),   # In1.Cu, GND
        DielectricLayer(thickness = ..., material = "FR4-Core", form = "core"),
        CopperLayer(thickness = 0.035, role = "signal"),   # In2.Cu
        DielectricLayer(thickness = ..., material = "2116", form = "prepreg"),
        CopperLayer(thickness = 0.035, role = "power"),    # In3.Cu, 3V3
        DielectricLayer(thickness = ..., material = "FR4-Core", form = "core"),
        CopperLayer(thickness = 0.035, role = "ground"),   # In4.Cu, GND
        DielectricLayer(thickness = ..., material = "3313", form = "prepreg"),
        CopperLayer(thickness = 0.035, role = "signal"),   # B.Cu
    ],
)
CONFIG = BoardConfig(stackup = STACKUP, design_rules = ...)
```

The dielectric thicknesses are the fab's for that stackup (1 oz inner
changes them from the 0.5 oz stack's). The impedance classes' widths
(`50Ohm SE`, `90Ohm Diff`) depend on them, so they are re-checked against
the fab's impedance calculator.

**2. Name the pair nets in their class:**
`USB_PAIR_CLASS = NetClass(name = "90Ohm Diff", ..., nets = ["USB_D_P", "USB_D_N"])`.

**3. Delete the retired keys from placemat.toml:** `[check] copper_oz`,
`[route] layers` and `[route] diff_pairs`. A run refuses them, naming what
replaces each.

**4. Set fab-profile.json's `via` and `min`** from the fab's capability page,
each via type `"yes"`, `"no"` or `"if-needed"`.

**5. Regenerate the board and run `placemat facts`.** Check each layer's
role and weight and the pairs, then `placemat facts --confirm`.

What moves:
- the route step's layers come from the roles;
- the pairs come from the classes;
- inner-layer current paths are judged by the inner constant and the
  layer's weight.

So a board's route and current-path verdicts can change on this release.

## Verification

- Stackup read:
  - a board with 0.5 oz inner copper judges an inner track's current path
    with the inner constant and 0.5 oz;
  - an outer track keeps the outer constant.
- Retired keys: each of the three in placemat.toml is refused, naming its
  replacement.
- Route layers: a board with F signal, In1 ground, In2 signal, In3 power,
  In4 ground, B signal routes on F, In2 and B.
- Pairs:
  - a two-net pair class pairs its nets whatever their names;
  - a four-net class pairs by `pair_key`;
  - the Default class makes no pair;
  - a board with no pair class has none.
- Fab minimums: a net class below `min.track_mm` is a `fab` finding.
- `placemat facts`:
  - a board with no fab-profile `via` is unconfirmed;
  - `--confirm` writes the digest;
  - a changed copper weight makes it unconfirmed again, and the run says
    so;
  - a `signal` layer carrying a `plane()` is flagged;
  - a board never confirmed has every fact unconfirmed.
- Shorten:
  - with blind `"yes"`, a cell whose GND drop field lies under a far-face
    pad places, its drops written as KiCad blind vias of the right span;
  - with `"if-needed"`, the same cell is refused, with the step note and a
    `needs` finding naming the count, net, span and fab-profile key;
  - with `"no"`, the refusal is as today.
- Migration: `allow_*` keys read as before; the digest parity tests pass.
- Skill: a pressure test of the new step. A session given a board with no
  fab-profile `via` section asks before placing, writes each answer in its
  home, and does not write a default.
