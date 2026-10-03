# Searched suggestions: what the studio page needs to build

The engine side (phase 6) is on `suggestions-phase6`. This note is the contract for the studio page; nothing here is built in
`studio_page.html`.

## What a searched suggestion looks like in the plan

A finding's `suggestions[i]` with `how: "searched"` has no value in its `edits` (the edit has no `value`) and a `figure`
(`api.md`, "Findings and severities"). Show it under the instant ones as a question, its `text` ("Changing the chamfer of the A
track might fix this: search options?"), with one button, "Search options". It has no Show, Try or Apply: `POST /suggest/show`,
`/try` and `/apply` answer 422 for it ("... is a searched suggestion: it has no value yet ...").

`figure.kind` is `bisect` (`declared`, `far`, `lo`, `hi`, `unit`, `direction`) or `set` (`values`, `enum`). `figure.what` names what is varied.

## Starting a probe

`POST /suggest/probe` `{"resolve": <resolve id>, "id": "s3a", "yes": false}` (the token as for the other suggestion endpoints).

- `{"state": "confirm", "estimate": {...}, "line": "..."}`: every candidate resolves the whole board. Show `line` (it says the
  candidate limit, the seconds each, and the total) on a confirmation; on yes post again with `"yes": true`. Nothing was started.
- `{"state": "started", "pid", "estimate", "line"}`: a command (`apply s3a --search --yes`) is running. It appears in
  `/commands` and on the live stream like any command, with `command: "apply"`.
- 409: a probe is already running, no script chosen, or the resolve worker/Popen failed. 422: not a searched suggestion. 404: no such
  suggestion in that resolve.

## Following it

The command's events (`cmdev`, and `GET` of the command's detail) are:

- `probe`: `{id, text, figure, budget_s, candidates}`. Draw the figure's range: `lo` to `hi` for a bisect (mark `declared` as "does
  not clear"), the members for a set.
- `candidate`: `{id, value, cleared, gained: [{kind, cause, subject, severity}], score, seconds, acceptable, n, of, saved, error?}`.
  Place each on the range as it arrives: cleared or not, with what it gained. `saved` is a result taken from an earlier probe.
- `probe_done`: `{id, state, n, of, best: {value, ...}|null, neighbour: {value, cleared}|null, monotone, message, resumed,
  candidates: [...]}`. `state` is `found`, `none`, `limit`, `budget`, `stopped` or `error`. Word it from `state` and `best` (the engine's
  `probe.line(event)` has the console wording to copy).

The command summary has `probe: {start, candidates: [...], done}`, so a page that opens late has the whole run.

## Stopping

`POST /suggest/probe/stop` sends SIGTERM to the command: it stops after the candidate in hand, keeps its results, sends
`probe_done` with `state: "stopped"` and exits. 409 where none is running.

## The result

A found value is a new instant suggestion `s3a.1` in `.placemat/suggestions.json` (shown by `placemat apply s3a.1`). The studio's
plan does not know it: after `probe_done` with `best`, read it (`suggestions.recall(board_dir, script)`, or add an endpoint) and show
it under the searched one with the usual Show, Try and Apply. Its digests are those of the plan the probe ran on; an edit to the script
since makes Apply refuse as for any suggestion.

Run the probe's `--search` again (the same button) to continue a stopped one: it uses the saved results and resolves no value
again; a changed script starts fresh and says so on the console.
