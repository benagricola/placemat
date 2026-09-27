# Model Paths Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When placemat writes a board, a footprint's 3D model path that does not resolve from the board's project folder is re-anchored to the nearest ancestor folder holding the same tail, written `${KIPRJMOD}`-relative.

**Architecture:** A pure function `models.reanchor(text, project_dir, stop)` decides one path; `write.apply_plan` walks every footprint's models through it and records what it did on the plan (`plan.models`); the runner prints one line.

**Tech Stack:** Python 3.12, pcbnew (`FOOTPRINT.Models()`, `FP_3DMODEL.m_Filename`), pytest.

**Spec:** `docs/superpowers/specs/2026-09-27-model-paths-design.md` (approved 2026-09-27)

## Global Constraints

- Only `${KIPRJMOD}`-relative and relative paths are touched; a path that resolves, a path under any other `${...}` variable, and an absolute path are left as they are.
- The search runs from the project folder up to the workspace root (the nearest `pcb.toml` declaring `[workspace]`, as `project.generator_inputs` finds it) or the filesystem root, and takes the first hit.
- The written form is `${KIPRJMOD}/` + the POSIX relative path from the project folder.
- Generic wording; plain ASCII; no tool or session references in commits.

## Review Focus

1. A path with `${KIPRJMOD}` and backslashes (a board edited on Windows): the tail still matches.
2. A tail found in the project folder itself (no `..` at all).
3. A footprint with several models: each is judged alone.
4. A run whose layout folder is written twice (a failed run restored, then written): re-anchoring an already re-anchored path is a no-op.
5. The generation cache is not touched: only the written board changes.

---

### Task 1: `models.reanchor`

**Files:** Create `src/placemat/models.py`; Test `tests/test_models.py`.

- [ ] **Step 1: Failing tests** (tmp_path trees): a tail two folders up is written `${KIPRJMOD}/../../parts/p/f.step`; a resolving path returns None (unchanged); `${KICAD9_3DMODEL_DIR}/x.step` and `/abs/x.step` return None; an unfound tail returns None and is reported missing; the search stops at a `pcb.toml` with `[workspace]`; backslashes are read as separators.
- [ ] **Step 2: Run** `uv run pytest -q tests/test_models.py` - FAIL (no module).
- [ ] **Step 3: Implement** `reanchor(text, project_dir, stop=None) -> tuple[str | None, bool]` (the new text or None, and whether the model was found at all) and `workspace_root(start) -> Path | None`.
- [ ] **Step 4: Run** - PASS. **Step 5: Commit** "models: a model path re-anchored to the folder that holds it".

### Task 2: The writer, the run line, docs

**Files:** Modify `src/placemat/kicad/write.py` (`apply_plan`), `src/placemat/layout.py` (`Plan.models: dict`), `src/placemat/runner.py` (a `models` line); docs (`api.md` "the files placemat writes" note, `migration.md` To 0.44, `BACKLOG.md` Done); Test `tests/test_models_kicad.py`.

- [ ] **Step 1: Failing KiCad test:** a copy of the breakout in `tmp/a/b/layout/`, a `parts/p/f.step` at `tmp/`, one footprint's model set to `${KIPRJMOD}/../parts/p/f.step` (one level short) with pcbnew; `apply_plan` with a resolved plan: the written board's model reads `${KIPRJMOD}/../../../parts/p/f.step` and `plan.models == {"reanchored": 1, "missing": []}` (plus the board's own models' tally).
- [ ] **Step 2: Implement:** in `apply_plan`, after placing and before `save`, for each footprint and each model, `reanchor(m.m_Filename, pcb dir, workspace_root(pcb dir))`; set `m.m_Filename` when a new text comes back; count and collect the missing (file names, first five). The runner says `models: N re-anchored, M not found (a, b, ...)` when either is non-zero.
- [ ] **Step 3: Run** the new tests and the full suite. **Step 4: Commit** "A written board's model paths resolve from its own folder".
