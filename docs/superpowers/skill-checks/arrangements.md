# Skill check: arrangements

The check asks whether an agent that has only the placemat skill and a module with no layout script
declares arrangements the way the skill's "Arrangements" section says to. It is run on at least two fixture
modules, and each run's transcript is kept in `transcripts/<module>.md`.

A failure is a change to the skill's wording, not to the check.

## Modules

The modules come from the fixtures that `tests/real_modules.py` stages. Between them they cover the four
roles the criteria depend on. The part names of each role are in `ROLES` in `fixtures/skill_check.py`, taken
from `placemat parts` of the module's generation.

| Module | Bypass | Pull-up | Polarised | Protruding |
| --- | --- | --- | --- | --- |
| usb5v | c_hf1, c_hf2 | | bulk_a, bulk_b | |
| usbtcpc | c_vdd | r_irq | | r_vconn |

In usb5v the two reservoirs stand past the rest on the east side, but they are polarised, so they are listed
under that role only. In usbtcpc the VCONN resistor stands about 1.2 mm past every other part on the west side
once the module is laid out.

## Running it

1. Stage the module: `python fixtures/skill_check.py stage <module> <scratch dir>`. This copies the fixture
   module and its generation without its layout script, and prints the task text. The other modules of the
   fixture folder, and their layout scripts, are left out.
2. Give the printed task to a fresh agent with `skills/placemat/SKILL.md` and `skills/placemat/references/`
   and nothing else. It lays the module out and finishes.
3. Run the checker on the script it wrote: `python fixtures/skill_check.py check <module> <script>`.
4. Read the transcript against the criteria below. Save it to `transcripts/<module>.md`.

## Criteria

Checked by `fixtures/skill_check.py check`:

- each `bypass` and `pullup` part has an alternative, as an `alternative` call or an `Alt` in an
  `arrangement`;
- no `polarised` part has one;
- each `protruding` part has an alternative, or the script has a `# extent: <part> ...` comment line giving the
  reason it has none;
- no option or group is named `alt` or `alt<number>`;
- no item has more options than `place.arrangement_options_max` (the item's own place counts as one).

Read from the transcript:

- the agent ran the module;
- it read the run's arrangement report (`arrangements` in `run.json`, and the `arrangement.refused` and
  `arrangement.limit` findings), refused alternatives included;
- for each refused alternative it fixed the alternative or dropped it, and did not finish with one refused;
- it declared a mirrored group where one is natural;
- it stayed within `place.arrangements_max` for the module, the product counted;
- an extent-setting member with no alternative has its reason in the run notes, not only in a script comment.
