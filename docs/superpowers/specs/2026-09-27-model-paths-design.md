# 3D model paths that resolve from any project depth

Date: 2026-09-27
Status: approved 2026-09-27
Source: a board's layout work, 2026-09-27: "module renders show no bodies"

## The problem

A board's parts normaliser writes each footprint's 3D model as
`${KIPRJMOD}/../../../parts/<part>/<file>.step`. That resolves for a project
at `boards/<board>/layout`. A module whose project sits two folders deeper
(`boards/<board>/modules/<name>/layout`) gets the same text, which points at
a folder that does not exist, so `kicad-cli pcb render` of the module draws
no bodies. One `${KIPRJMOD}`-relative prefix cannot serve two depths, and
the path comes from the part library, not from the script.

placemat writes the board after the generator (`apply_plan`), and leaves
model paths as the generator wrote them.

## The change

1. **When placemat writes a board, each footprint model path that does not
   resolve is re-anchored.** A path is `${KIPRJMOD}`-relative or relative
   (KiCad resolves both from the project's folder). Leading `..` parts are
   stripped to give its tail (`parts/<part>/<file>.step`); the tail is looked
   for under the project's folder and then each folder above it, up to the
   workspace root (the nearest `pcb.toml` declaring `[workspace]`) or the
   filesystem root; the first hit is written back as `${KIPRJMOD}/` plus its
   path relative to the project's folder.
2. **Everything else is left as it is:** a path that resolves, a path under
   another variable (`${KICAD9_3DMODEL_DIR}` and the like: KiCad's own
   libraries), an absolute path, and a path whose tail is found nowhere.
3. **The run says what it did:** one log line, "models: N re-anchored, M not
   found (<first few files>)", only when N or M is not zero.
4. A parent board that stamps a module gets the module's footprints with
   the module's paths; its own write re-anchors them to its own depth, so
   each board's file is right for its own folder.

## Verification

- Pure test of the path function: a tail found two folders up is written
  `${KIPRJMOD}/../../parts/...`; a resolving path, a `${KICAD9_...}` path,
  an absolute path and an unfound tail are unchanged; the search stops at a
  `pcb.toml` with `[workspace]`.
- KiCad test: a copy of the breakout with one footprint's model set to a
  path one level too shallow, and the file present at the right depth:
  after `apply_plan`, the written board's model path resolves.
- Bench unaffected (no placement change); no bench run needed beyond the
  suite.

## Not in scope

- Rewriting paths that resolve but point at a different copy of the file.
- Model offsets, scales and rotations.
