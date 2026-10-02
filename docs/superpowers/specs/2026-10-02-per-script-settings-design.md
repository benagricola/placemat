# Per-script settings

## Problem

A project keeps one `placemat.toml` for a parent board and about thirty module
scripts. One setting has to differ per script: the parent needs
`[solve] enabled = false`, one module does better with it true. Settings are
resolved per board directory, so the only way to differ was a `placemat.toml`
in the module's own folder. That broke the module's imports: a script's
importable folders ran up to the nearest `placemat.toml`, so the module's own
file cut it off from the shared helper in the parent's folder.

## Design

### The override table

A script's path relative to the `placemat.toml` holding the table is the key,
as `[facts.boards]` does, and the section follows it:

```toml
[solve]
enabled = false

[scripts."modules/m/M_layout.py".solve]
enabled = true
```

TOML reads this as `scripts -> path -> section -> key`, so the body is the
base document's own shape and is parsed by the same `_flatten` and checked by
the same `_validate`: unknown sections and keys, wrong types and values under
their floor are refused. Further refusals: a path that names no file beside
the toml (a stale or mistyped key would quietly do nothing), and a `facts`
section (placemat's own record, never per script). Every table is validated
whichever script is running.

`settings.load(start, overrides, script=None)` applies, in order: defaults,
every file's base values (nearest wins), then for each file farthest first the
table naming `script`, then CLI flags. A script is matched against each file
by its path relative to that file. A source reads
`<file> [scripts."<path>"]`.

Callers that know the script pass it: run, preview, freeze, lock, facts,
route, check, settings, measure and the other commands given a script.
Commands given only a board file get the base settings.

### Run id and reuse

The run id and the reuse digest are computed from the resolved settings
(`Settings.json()`), which now include the override, so no further change is
needed: two scripts that differ only in an override get different ids.

### Import dirs

`_import_dirs` ran from the script's folder up to the nearest `placemat.toml`.
It now runs up to the outermost one, the same file set `settings._files`
merges. The change is safe: the folders are added to `sys.path` only while the
script runs, innermost first, and the modules imported from them are dropped
afterwards; a name found in a nearer folder still wins. It also feeds
`script_fingerprint`, so a change to a helper above a nearer toml changes the
run id, as it should. A project with a `placemat.toml` far above its board
now makes the folders between importable; that file already contributes
settings to the run.

## Verification

- Two scripts sharing a toml with one override: each load sees its own value,
  the base applies to the other, a flag beats the override.
- An unknown key, unknown section, wrong type, missing script path, `[facts]`
  in an override, and a bare `[scripts]` value are errors naming the file.
- Run ids differ when only the override differs.
- `placemat settings <script> --json` shows the override's source.
- A module with its own `placemat.toml` still imports the parent's helper, and
  the fingerprint follows that helper.
- Full suite and bench: no placement change for a project without a `scripts`
  table.
