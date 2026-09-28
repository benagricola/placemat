# Current Path Between Carriers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `check current-path` judges each pair of carrying parts at the lesser of their currents by the widest route between them, with zones in the net's copper, and does not judge a net whose carriers no copper joins yet.

**Architecture:** In `src/placemat/checks.py`: `_net_graph` adds each zone's fill per layer as a node (width: its narrowest neck); `current_paths` collects per net each carrier's current (above zero only); `_load_path` becomes `_worst_pair(geometry, net, carriers: {ref: amps})`, which for each pair runs the widest-route search from one's pads and takes the best of the other's pads, judges it against `ipc2221_width_mm(min(amps))`, and returns the pair with the lowest width over need (or the not-joined case). One carrier keeps its widest route to any other part.

**Tech Stack:** Python 3.12, pytest (pure, synthetic geometry).

**Spec:** `docs/superpowers/specs/2026-09-28-current-path-terminals-design.md` (approved 2026-09-28)

## Global Constraints

- A zone node's width is `neck_mm` of its fill outline on that layer.
- The verdict's note names the pair (pad labels), the current it was judged at, the rise and the copper weight.
- Not joined: `ok=None`, note "no copper joins A and B on NET yet".
- Generic wording; plain ASCII; no tool or session references in commits.

## Review Focus

1. A net with three carriers where one pair has no copper yet and another pair is judged: the judged pair decides, the unjoined one is said.
2. A zone fill of many outlines on one layer (a split pour): each outline its own node.
3. A pad inside a zone fill: the zone touches it (fills pull back round other nets, not their own).
4. A carrier with no pad on the net's copper at all.
5. The pour fallback for a net with pours but no carriers joined.

---

### Task 1: The check

**Files:** `src/placemat/checks.py`; Tests `tests/test_current_path_pairs.py`, `tests/test_checks.py` (changed where it encoded the old fallback, listed in the commit).

- [ ] Failing tests per the spec's verification; implement; the check tests pass; docs (`api.md` check paragraph, `skills/placemat-design/SKILL.md` `Pm.I`, `migration.md` To 0.50, `BACKLOG.md`); full suite; **commit** "check current-path judges each pair of carriers at what can flow between them".
