# Accepting one check verdict, with a reason

Status: draft, for approval.

Source: Ben, through a board's session (2026-10-01).

## Problem

A design check can fail where no layout can do better, and a script has no
way to say so for that one verdict. The board-wide knobs (`check.limits`,
`--rise`, `--keep-out`) loosen the check everywhere. Cases from one boost
converter module:

- `current-path VOUT`, 0.35 mm against 1.37 mm: the route is measured into a
  pin 0.5 mm from its neighbours, so the package's pitch sets the width; the
  exposed pad carries the current in parallel.
- `current-path SW2`, 1.01 mm against 1.76 mm: the neck is between two
  tracks beside the pins, again set by the pitch.
- `keep-out SW2`: the check's own note says the part's pads are 0.48 mm
  apart, a distance its footprint sets, and it fails anyway.

The run reports these as FAIL on every run, so a real new failure reads the
same as the accepted ones. (A failed check costs nothing in the run's score
today; `checks_failed` is a metric only. This is about what the run says.)

## Design

```python
board.accept("current-path", "VOUT", at_least=0.35,
             why="into pin 11, 0.5 mm from pins 10 and 12: the package's pitch sets it; "
                 "the exposed VOUT pad carries the current in parallel")
board.accept("keep-out", "SW2", at_least=1.0, why="...")
board.accept("heat", "U3", at_most=118.0, why="...")
```

`board.accept(check, subject, *, at_least=None | at_most=None, why)` accepts
the verdict a check gives `subject`: the net, part or loop the verdict names
(its `subject`, as the run prints it). Exactly one bound, on the side the
check judges:

- `at_least=` for checks where more is better: `keep-out`, `current-path`.
- `at_most=` for checks where less is better: `crossings-under`, `heat`,
  `exposure`, `hot-loop`, `switch-node`.

A `why` is required.

### Judged

After the checks run, each failed verdict whose check and subject an
acceptance names is judged against the acceptance's bound instead of the
check's limit:

- Within the bound: the verdict is **accepted**. It reads
  `accepted (<bound>): <why>` in place of FAIL, counts as accepted (not
  failed) in the run's check line, and `checks_accepted` joins
  `checks_failed` in the metrics.
- Past the bound: it fails as before, its note adding "past its acceptance
  of <bound>: <why>". The acceptance covers what was judged, not anything
  worse.

An acceptance that names no verdict the run produced (a check or subject
the board does not have, or no longer has) is a `setup` finding, so stale
ones get noticed. One whose verdict passes on its own is a `setup` finding
too ("not needed: the check passes").

### Recorded

The run log prints every acceptance and what it matched after the check
line, and `run.json` carries them (`acceptances`: check, subject, bound,
why, the verdict's value, and accepted / past / unmatched / not needed), so
a reviewer sees all of them in one place.

`placemat check` on a board without its script knows no acceptances and
judges as today.

### Refused

At declaration: an unknown check name; neither or both bounds; the bound on
the wrong side for the check; an empty `why`; the same check and subject
accepted twice.

## Verification

- A failing `current-path` accepted at its value: reads accepted with the
  why, counted as accepted, not failed.
- The same acceptance after the copper gets narrower than the bound: fails,
  the note naming the acceptance.
- `at_most=` on `heat`: accepted within it, failing past it.
- An acceptance for a subject the board has no verdict for: a `setup`
  finding; one whose verdict passes: a `setup` finding.
- `run.json` lists each acceptance with its outcome; the run log prints
  them.
- Each refusal.
- Digest parity: a script without `board.accept` digests as before; an
  acceptance does not change any placement or copper.
