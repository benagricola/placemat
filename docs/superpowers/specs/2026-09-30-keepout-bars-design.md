# A keepout that names what it bars

Status: approved (2026-09-30).

Source: the owner, through a board's session (2026-09-30).

## Problem

A keepout says what it admits: `allow=` names parts, cells and nets let in,
`max_height=` admits parts short enough. A region that must bar only a few
parts (a cup under a part mounted off the board, which only that part and
its own pins may not share) has to name every other part on the board in
`allow=`: hundreds of references in the script, the `.kicad_dru` rule and
the label, and a new part added to the board is barred until the script
names it too.

## Design

`board.keepout(..., bars=(Part(...), Cell(...)))` names the parts the
region keeps out. Every other part is let in.
- `bars=` and `allow=` of parts or cells do not go together: a keepout
  says one side. Declaring both is refused.
- `allow=` of nets still lets copper through, as today.
- `bars=` with `max_height=`: the parts named are barred whatever their
  height, and every other part is judged by the height. So `bars=` is a
  stricter set on top of the height rule.
- A `Cell(...)` in `bars=` bars every member.

**Placement.** The reservation admits every part but the barred ones. It
is the same reservation as today, with its admitted set taken as the
complement, worked out when the board is read, so a part added later is
admitted without an edit.

**KiCad.** The rule area allows footprints, as an admitting keepout's
does (0.61, amendment 1b). The `.kicad_dru` rule forbids exactly the
barred references:
`(condition "A.intersectsArea('keepout cup') && (A.Reference == 'M1' ||
A.Reference == 'J1' || A.Reference == 'J2')")`.

**Label.** `cup: bars M1, J1, J2`, within `write.keepout_label_refs`, else
a count.

## Verification

- A keepout with `bars=(Part("m1"),)` refuses M1 and admits every other
  part.
- A part added to the board is admitted with no change to the script.
- `bars=` with `max_height=`: a short barred part is refused, a short
  other part admitted, a tall other part refused.
- `bars=` with `allow=` of parts is refused at declaration.
- The written board: a rule area allowing footprints, a rule naming
  exactly the barred references, and KiCad's own DRC reports a barred
  part inside and not another.
- The label says `bars ...`.
- Digest parity: a script without `bars=` digests as before.
