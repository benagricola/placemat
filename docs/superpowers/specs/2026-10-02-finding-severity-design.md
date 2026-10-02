# Finding severity

Follows the finding kinds of `findings.py`, which say what sort of thing went
wrong and let the run score count it, but not how much it matters.

## Problem

A run prints every finding alike. "vias environment: 1 GND via shared, 1 moved
0.35 mm under cell X's U2" is placemat doing what it is built to do, and "escape_walled
U1 pin 8 (GND): walled off by R2, U1" can stop the board routing, yet they read as
the same line, and the printed list is cut at eight, so a long run of notices
can hide the one finding that needs a person. The kind is no help: a kind says
what the finding is about, and several kinds hold both sorts (`vias` shared or
moved against dropped, `copper` a conflict against a note on what was drawn,
`setup` a web under the milling minimum against an unneeded `accept`).

## Design

### Severities

Each finding has a `severity`, one of:

- `notice`: placemat did something by design that the user may want to know:
  a via shared or moved by give-way, a look-ahead dropped, an adopted route
  routed again.
- `warning`: a quality issue the board can live with, or one a person should
  judge: a link over its limit, a label on a part, a declared track not drawn.
- `critical`: the board cannot be built or fully routed as it is: an item
  unplaced, copper that conflicts, a pad walled in, a rule below the fab's
  minimum.

### Where it lives

`findings.py` holds `SEVERITIES` (least to most serious), `SEVERITY` (a table
from kind to its default) and `Finding(kind, text, severity=None)`. A finding of
a kind that holds one case takes the table's severity. Where a kind mixes
cases, the code that makes the finding passes its own severity, at the point
it knows which case it is. The table is a classification of what a kind means,
not a scoring weight, so it stays in code and is documented in `api.md`
("Findings and severities"); there is no setting to override it. A board
that wanted a kind graded differently would be asking for a settings table
with these defaults; no case for one has come up.

`Findings` gains `by_severity()` and `most_serious_first()`; `summary()` gives
"1 critical, 2 warning, 4 notice". A finding without a recorded severity
(`DEFAULT_SEVERITY`) reads as `warning`.

### The table

| Kind | Severity | Why |
|---|---|---|
| `unplaced` | critical | an item with no place is not on the board |
| `fixed` | critical | a decided item (fixed, a cutout, a keepout) is not legal where it was put |
| `copper`, a conflict | critical | copper meets another net, crosses a keepout, passes a corner inside the clearance, or two tracks cross and neither may bridge |
| `copper`, a declared item not drawn | warning | the script's copper is missing; a person decides whether the router stands in |
| `copper`, a note on a choice placemat made | notice | a waypoint drawn pad to pad, stitch vias outside the region left out, the side a stitch row took, a track left out whose crossing is also a finding |
| `escape_walled` | critical | a pad with no way out cannot be routed |
| `escape_closed` | warning | the way toward what a pad joins is closed; other ways out remain |
| `escape_crossed` | warning | the router can usually separate two crossed escapes |
| `escape_lane` | warning | a declared lane is blocked; the router can find another |
| `pair_crossed` | warning | a pair's halves cross; a swap or turn fixes it |
| `link_over` | warning | a link longer than its limit |
| `label`, on a part or with no spot | warning | silk a person judges |
| `label`, not drawn because its item found no place | notice | the item's `unplaced` finding is the fault |
| `split` | warning | a cell in groups joined only by board-level nets |
| `facts` | warning | the facts differ from the last confirmation |
| `fab` | critical | the fab would refuse the net class |
| `setup`, a web round a cutout under the minimum; a net class that does not fit the pads' pitch | critical | the board cannot be milled, or the router cannot escape the pads |
| `setup`, an undeclared part; a reserved lane no track uses; a part outside its frame's reach; an `accept` matching no verdict | warning | the script is incomplete or wrong |
| `setup`, a layer a keepout or rule names that the board lacks; a rule not carried; a look-ahead dropped; an `accept` that was not needed | notice | placemat carried on without it |
| `route` | notice | an adopted route dropped because a part it joins moved; the router routes it again |
| `vias`, shared, moved, re-routed, left its pad, shortened, a field re-laid | notice | carried vias gave way as designed |
| `vias`, a via dropped or a field drawn with fewer vias than declared | warning | fewer vias than were declared |
| `needs` | notice | an if-needed fab option would have cleared a spot; the item's `unplaced` finding is the fault |

Design-check verdicts are not findings and keep their own pass/fail. A failed
verdict now has a severity too (`checks.CHECK_SEVERITY`): `critical` for
`keep-out` and `current-path`, `warning` for the others; a passing or accepted
verdict has none. The failure line reads `FAIL [critical]`, and
`run.json`'s `verdicts` carry the field.

### Output

- `run` and `preview` print `[severity] sentence`, the most serious first (the
  run's list is cut at eight, so a critical finding is no longer hidden behind
  notices), coloured by severity. The count line says how many of each:
  `7 finding(s) (1 critical, 2 warning, 4 notice)`.
- `run.json` keeps `findings` as sentences, as before, and gains
  `finding_details`: `kind`, `severity` and `text` per finding in the same
  order. `RunRecord.findings_with_severity()` reads them, and for a record with
  no `finding_details` gives each finding as a `warning`.
- `preview --format json` gains `finding_details` and keeps `findings` as
  sentences. The studio's plan JSON gives each finding a `severity` and
  `counts.severities`; the Findings tab lists the most serious first with a
  severity chip.
- The reuse cache stores `[kind, text, severity]`; an entry without the third
  field takes its kind's default.

### Scoring

Unchanged. `score.py` counts findings by kind. Two kinds of notice are scored as
faults today, and are named here to decide, not changed: the `copper` notices
(a waypoint drawn pad to pad, stitch vias left out, the stitch row's side, a
track left out whose crossing is also a finding) each count `score.copper`
(200 mm), and a `label` "not drawn" counts `score.label` (50 mm). The track-left-out
note counts on top of the crossing finding that caused it. Counting by severity
(a notice scores nothing) would be a change to run scores and the stored best,
and needs the bench re-baselined.

## Verification

- `tests/test_finding_severity.py`: every kind has a severity; a finding takes
  its kind's unless told; the severity survives a pickle and the reuse cache; the
  vias examples (a share, a move, a re-laid field) are notices and a field that
  dropped vias a warning; a pad walled in is critical; an unplaced item is
  critical, a link over its limit a warning; the plan JSON, `preview --format json`
  and the printed lines carry the severity, most serious first; a run record
  keeps it and an old one reads as warnings; a failed `keep-out` check is
  critical.
- The existing suites for findings, give-way, checks, reuse, the studio and
  the report pass.
- `fixtures/bench.py --jobs 2`: no score moves.
