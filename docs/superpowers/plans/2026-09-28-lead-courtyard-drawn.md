# Plated lead and courtyard under the physical envelope - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Under the physical envelope, a part's courtyard is kept off another part's plated leads, both ways, as KiCad's `pth_inside_courtyard` judges it, in Python and natively.

**Architecture:** A drawn part's courtyard under `physical` becomes a `yard`: a shape of a kind that conflicts only with another owner's plated lead. Yards are not in `ItemGeometry.shapes` (so no measure that unions a part's shapes changes); they are computed on demand from the part's read courtyard and its current placement (as `pad_anchor` moves a pad), joined to the obstacle lists and to the candidate's legality shapes only. The native conflict learns the kind, so the native index and sweep judge it with the rest.

**Tech Stack:** Python (placemat), Rust (native/src/shapes.rs via pyo3), pytest.

**Spec:** docs/superpowers/specs/2026-09-28-lead-courtyard-drawn-design.md

## Global Constraints

- Generic wording in source, tests' docstrings aside: no module, part or board names.
- Plain ASCII.
- Every placement change runs `fixtures/bench.py`; tally in the commit; `--update` when a number changes.
- Commit with `git -c user.name="<owner name>"`; no Claude/Anthropic/session reference.
- Rebuild native with `uv pip install -q -e ".[native]"` after a Rust change.

## Rulings made while planning

- `union` already claims the courtyard (`_fp_shapes`, occupancy.py:214: `envelope != "physical" or not drawn`), so the existing lead rule applies there; only `physical` with a drawn part (silk or fab) lacks it. The yard applies exactly where `_fp_shapes` leaves the courtyard out.
- One rule, one sentence: the refusal is the existing lead sentence with the pad added, for both envelopes: "C16 courtyard sits over the through-hole lead of J1 pad 2" (the spec's example wording, in the existing sentence's form).
- A board with no plated leads gets no yards (spec item 2's "pays nothing").

## Review Focus

1. A cell under physical: its members' yards move with the cell (candidate) and stand where the members were committed (obstacle).
2. A part flipped to the back: its yard's face flips; a through lead is on both faces, so the rule fires either way.
3. A blocker for a candidate lead against a placed yard is counted as `courtyard`, not as an unknown kind.
4. Python fallback (no native) reach: a yard reaching past the item's extent still finds the lead.
5. Native/Python parity over the bench's physical configuration (existing test_native_sweep, test_native_legal parity tests).

---

### Task 1: The yard kind in the native conflict

**Files:**
- Modify: `native/src/shapes.rs` (Kind enum, from_str, conflict, tests)

- [ ] **Step 1: failing Rust tests** in shapes.rs's test module:

```rust
    #[test]
    fn a_yard_over_another_parts_lead_conflicts() {
        let yard = shape(Kind::Yard, "C1", rect(0.0, 0.0, 2.0, 2.0), 1, 0, "", true);
        let lead = shape_ex(Kind::Through, "J1", rect(0.5, 0.5, 0.3, 0.3), 3, 0xFFFF_FFFF, "A", true, true);
        assert!(conflict(&yard, &lead, None, &cfg()));
        assert!(conflict(&lead, &yard, None, &cfg()));
    }

    #[test]
    fn a_yard_meets_nothing_but_another_parts_lead() {
        let yard = shape(Kind::Yard, "C1", rect(0.0, 0.0, 2.0, 2.0), 1, 0, "", true);
        let own = shape_ex(Kind::Through, "C1", rect(0.5, 0.5, 0.3, 0.3), 3, 0xFFFF_FFFF, "A", true, true);
        let via = shape_ex(Kind::Through, "", rect(0.5, 0.5, 0.3, 0.3), 3, 0xFFFF_FFFF, "A", false, false);
        let pad = shape(Kind::Pad, "R1", rect(0.5, 0.5, 0.3, 0.3), 1, 1, "B", true);
        let body = shape(Kind::Body, "R1", rect(0.5, 0.5, 0.3, 0.3), 1, 0, "", true);
        let other = shape(Kind::Yard, "R1", rect(0.5, 0.5, 0.3, 0.3), 1, 0, "", true);
        for o in [&own, &via, &pad, &body, &other] {
            assert!(!conflict(&yard, o, None, &cfg()));
        }
    }
```

- [ ] **Step 2:** `cd native && cargo test --lib yard` -> FAIL (no `Kind::Yard`).
- [ ] **Step 3:** add `Yard` to `Kind`, `"yard" => Some(Kind::Yard)`, and at the top of `conflict`:

```rust
    if s.kind == Kind::Yard || o.kind == Kind::Yard {
        // Occupancy's yard: a drawn part's courtyard under the physical
        // envelope, judged only against another part's plated lead.
        let (yard, other) = if s.kind == Kind::Yard { (s, o) } else { (o, s) };
        return other.kind == Kind::Through && other.owner != yard.owner && other.is_lead
            && polys_overlap(&yard.poly, &other.poly);
    }
```

- [ ] **Step 4:** `cargo test --lib` -> PASS; rebuild native.
- [ ] **Step 5:** commit "native: a yard meets only another part's plated lead".

### Task 2: Yards in the occupancy

**Files:**
- Modify: `src/placemat/occupancy.py` (`__init__`, `_conflict`, `_native_bucket`, `obstacles`, `_native_obstacle_index`, legality origin shapes, `legal`, `legal_bucket`, `_native_origin_shapes`, `NativeSweeper`)
- Test: `tests/test_lead_yard.py`

**Interfaces:**
- Produces: `Occupancy._yard_refs: frozenset[str]`; `Occupancy._yard(ref) -> Shape` (kind "yard", at the part's current placement); `Occupancy._legal_origin_shapes(item, geom, placement) -> list[Shape]`.

- [ ] **Step 1: failing tests** (tests/test_lead_yard.py), all pure, physical envelope, both parts drawn (a fab box):
  - a capacitor (courtyard 1 mm past its body) searched next to a placed through-hole part, its body 0.3 mm clear of lead 2, its courtyard over it: `legal` refuses with "C1 courtyard sits over the through-hole lead of J1 pad 2";
  - the reverse: the capacitor placed, the through-hole part's lead under its courtyard: refused, naming C1's courtyard and J1 pad 2;
  - the same spots with no courtyard overlap (courtyard excess 0.1): legal;
  - a part's own lead under its own courtyard: legal (the through-hole part alone);
  - no plated leads on the board: `occ._yard_refs` is empty;
  - courtyard envelope: the first spot is refused by the existing rule, with the new sentence (pad named);
  - blame: the reverse case's blocker kind is "courtyard";
  - a cell of the capacitor and another part, searched next to the through-hole part: refused the same way;
  - parity: with the native module, `legal` via the native index equals `legal` with a plain list of obstacles (no `_native`), for a grid of candidates round the lead.
- [ ] **Step 2:** run -> FAIL.
- [ ] **Step 3:** implement:
  - `__init__`: `self._yard_refs = frozenset(fp.ref for fp in geometry.footprints if fp.silk or fp.fab) if self.envelope == "physical" and self._leads else frozenset()`.
  - `_yard(ref)`: the part's courtyard as `_fp_shapes` would claim it (drawn polygon or box), moved from where it was read to `self.items[ref].reference` (`_transform` of a read ItemGeometry, as `pad_anchor`), its face flipped when the part is; cached per (ref, reference).
  - `_conflict`: a yard against another owner's lead -> `_lead_sentence(yard, lead)`; a yard against anything else -> None; checked first. The courtyard branch's lead sentence uses `_lead_sentence` too.
  - `_native_bucket`: a yard -> "courtyard", checked first.
  - `obstacles` and `_native_obstacle_index`: append `self._yard(o)` for each placed owner in `_yard_refs` not in the skip set.
  - `_legal_origin_shapes`: `_origin_shapes` plus the item's own yards turned and faced at the origin, cached like `_origin_shapes`; used by `legal` (both paths), `legal_bucket`, `_native_origin_shapes`, `NativeSweeper.origin`. The Python path's reach includes the yards' boxes.
  - Blockers: a `yard` obstacle is counted as `courtyard`.
- [ ] **Step 4:** tests PASS; `uv run pytest -q tests/test_occupancy.py tests/test_native_*.py tests/test_occupancy_parity.py tests/test_flip_parity.py` PASS.
- [ ] **Step 5:** bench: `uv run python fixtures/bench.py` (tally; `--update` if physical numbers move; each change named). Commit "Under the physical envelope a courtyard keeps off another part's plated lead".

### Task 3: Docs and backlog

- [ ] api.md: the physical envelope paragraph says a drawn part's courtyard is still kept off other parts' plated leads, and the refusal names the pad.
- [ ] BACKLOG: the lead-vs-courtyard entry moves to Done (unreleased; 0.50).
- [ ] Full suite to a file; commit "Docs: the plated lead rule under the physical envelope".
