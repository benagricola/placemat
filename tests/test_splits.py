"""A cell of several jobs: placemat groups a cell's members by the nets
local to it and reports a cell of two or more groups as a `split` finding
(docs/superpowers/specs/2026-09-30-split-modules-for-placement-design.md,
section 2).

Every fixture board here is small (only what one test needs), so a net
that is meant to read as "board-level" must genuinely have a pad outside
the cell, or a pad on every member of the SAME cell with no outside pad at
all is indistinguishable, by pad count alone, from a real local net - a
free-floating net name with no second pad anywhere is not a useful stand-in
for "shared with the rest of the board" on a board this small. Most tests
below use `GND` (excluded because it is a declared plane, whatever its
pads) as the only non-local net, which sidesteps this; the one test that
also wants a genuine non-plane board-level net gives it a pad outside the
cell explicitly."""
import dataclasses

from placemat import splits
from tests.fixtures import board_geometry, footprint, pad


def _cell(*fps, width=80.0, height=80.0):
    named = [dataclasses.replace(fp, cell="m") for fp in fps]
    g = board_geometry(named, cells=["m"], width=width, height=height)
    return g, g.cells["m"]


def _with_pad(fp, number, net, dx, dy):
    """`fp` with one more pad, `dx`/`dy` off its centre."""
    cx, cy = fp.location.x, fp.location.y
    return dataclasses.replace(fp, pads=fp.pads + (pad(fp.ref, fp.inst, number, net, cx + dx, cy + dy),))


def test_two_independent_pairs_joined_only_by_a_plane_and_a_board_level_net_is_a_split_finding():
    # U1-R1 share L1; U2-R2 share L2; all four also carry GND (a plane,
    # excluded whatever its pads) and BUS - genuinely a board-level net
    # here, since J1, outside the cell, carries it too: neither GND nor
    # BUS is local, so it is exactly the two pairs.
    u1 = _with_pad(footprint("U1", 10, 10, nets=("L1", "GND")), 3, "BUS", 0.0, -0.5)
    r1 = _with_pad(footprint("R1", 10, 20, nets=("L1", "GND")), 3, "BUS", 0.0, -0.5)
    u2 = _with_pad(footprint("U2", 30, 10, nets=("L2", "GND")), 3, "BUS", 0.0, -0.5)
    r2 = _with_pad(footprint("R2", 30, 20, nets=("L2", "GND")), 3, "BUS", 0.0, -0.5)
    j1 = footprint("J1", 60, 10, nets=("BUS", "X"), cell=None)    # outside the cell
    named = [dataclasses.replace(fp, cell="m") for fp in (u1, r1, u2, r2)] + [j1]
    g = board_geometry(named, cells=["m"], width=90.0, height=90.0)
    text = splits.cell_text(g, g.cells["m"], plane_nets={"GND"}, min_group=2)
    assert text == (
        "its parts form 2 groups joined only by board-level nets: U1, R1; U2, R2. "
        "Parts with no close placement requirement in common may be split into modules of their own.")


def test_one_group_and_two_unjoined_parts_is_not_reported():
    # U1-R1 share L1 (one group); C1 and C2 carry only GND, on both pads -
    # a plane net, so C1 and C2 have no local net at all: unjoined.
    u1 = footprint("U1", 10, 10, nets=("L1", "GND"))
    r1 = footprint("R1", 10, 20, nets=("L1", "GND"))
    c1 = footprint("C1", 30, 10, nets=("GND", "GND"))
    c2 = footprint("C2", 30, 20, nets=("GND", "GND"))
    g, cell = _cell(u1, r1, c1, c2)
    assert splits.cell_text(g, cell, plane_nets={"GND"}, min_group=2) is None


def test_a_plane_net_shared_by_every_member_joins_nothing():
    # Every pad on the board is GND, declared a plane: no local net at
    # all, so there is nothing to group.
    u1 = footprint("U1", 10, 10, nets=("GND", "GND"))
    r1 = footprint("R1", 30, 10, nets=("GND", "GND"))
    g, cell = _cell(u1, r1)
    assert splits.cell_text(g, cell, plane_nets={"GND"}, min_group=2) is None


def test_a_net_with_a_pad_outside_the_cell_joins_nothing():
    # U1 and R1 both carry L1, but so does an outside part: L1 is not
    # local, so U1 and R1 do not group on it.
    u1 = footprint("U1", 10, 10, nets=("L1", "X"))
    r1 = footprint("R1", 30, 10, nets=("L1", "Y"))
    outside = footprint("J1", 60, 60, nets=("L1", "Z"), cell=None)
    named = [dataclasses.replace(u1, cell="m"), dataclasses.replace(r1, cell="m"), outside]
    g = board_geometry(named, cells=["m"], width=80.0, height=80.0)
    assert splits.cell_text(g, g.cells["m"], plane_nets=set(), min_group=2) is None


def test_split_min_group_three_drops_a_finding_whose_groups_are_pairs():
    u1 = footprint("U1", 10, 10, nets=("L1", "GND"))
    r1 = footprint("R1", 10, 20, nets=("L1", "GND"))
    u2 = footprint("U2", 30, 10, nets=("L2", "GND"))
    r2 = footprint("R2", 30, 20, nets=("L2", "GND"))
    g, cell = _cell(u1, r1, u2, r2)
    assert splits.cell_text(g, cell, plane_nets={"GND"}, min_group=3) is None


def test_the_message_names_groups_in_cell_order_and_the_unjoined_parts():
    # Three groups (3, 2, 2 members): L1 joins U3/C7/R2, L2 joins U5/R4, L3
    # joins Q2/R9. C1, C2, C3, R1 carry only GND, on both pads, like a
    # bypass capacitor tied straight across the plane: no local net, so
    # unjoined. Matches the spec's own example text (section 2).
    u3 = footprint("U3", 10, 10, nets=("L1", "GND"))
    c7 = footprint("C7", 10, 20, nets=("L1", "GND"))
    r2 = footprint("R2", 10, 30, nets=("L1", "GND"))
    u5 = footprint("U5", 30, 10, nets=("L2", "GND"))
    r4 = footprint("R4", 30, 20, nets=("L2", "GND"))
    q2 = footprint("Q2", 50, 10, nets=("L3", "GND"))
    r9 = footprint("R9", 50, 20, nets=("L3", "GND"))
    c1 = footprint("C1", 70, 10, nets=("GND", "GND"))
    c2 = footprint("C2", 70, 20, nets=("GND", "GND"))
    c3 = footprint("C3", 70, 30, nets=("GND", "GND"))
    r1 = footprint("R1", 70, 40, nets=("GND", "GND"))
    g, cell = _cell(u3, c7, r2, u5, r4, q2, r9, c1, c2, c3, r1, width=100.0, height=100.0)
    text = splits.cell_text(g, cell, plane_nets={"GND"}, min_group=2)
    assert text == (
        "its parts form 3 groups joined only by board-level nets: U3, C7, R2; U5, R4; Q2, R9 "
        "(and 4 parts no net inside the cell joins to the others: C1, C2, C3, R1, "
        "each placed by the pin it serves or the part it senses, not a split candidate). "
        "Parts with no close placement requirement in common may be split into modules of their own.")


def test_an_unconnected_pad_does_not_join_two_real_groups_via_an_empty_net():
    # U1 and U2 each carry a third, unconnected pad (net ""). If "" were
    # wrongly counted as a real, shared net, U1 and U2 would be joined
    # through it into one group of four, and this would report no finding
    # at all - so this pins that "" is filtered, not just that nothing
    # crashes.
    u1 = _with_pad(footprint("U1", 10, 10, nets=("L1", "GND")), 3, "", 0.0, -0.5)
    r1 = footprint("R1", 10, 20, nets=("L1", "GND"))
    u2 = _with_pad(footprint("U2", 30, 10, nets=("L2", "GND")), 3, "", 0.0, -0.5)
    r2 = footprint("R2", 30, 20, nets=("L2", "GND"))
    g, cell = _cell(u1, r1, u2, r2)
    text = splits.cell_text(g, cell, plane_nets={"GND"}, min_group=2)
    assert text == (
        "its parts form 2 groups joined only by board-level nets: U1, R1; U2, R2. "
        "Parts with no close placement requirement in common may be split into modules of their own.")


def test_a_member_whose_only_local_net_touches_nobody_else_is_listed_with_the_unjoined_parts():
    # U1-R1 share L1 (group 1); U2-R2 share L2 (group 2): a real finding.
    # Q1's own net Q_ONLY has no other pad anywhere on the board, so it IS
    # local to the cell (every pad of Q_ONLY - there is one - sits on the
    # cell), but joins nobody: a group of one, always below the floor of
    # 2, so it is listed with the parts no local net joins to another, not
    # as a third group.
    u1 = footprint("U1", 10, 10, nets=("L1", "GND"))
    r1 = footprint("R1", 10, 20, nets=("L1", "GND"))
    u2 = footprint("U2", 30, 10, nets=("L2", "GND"))
    r2 = footprint("R2", 30, 20, nets=("L2", "GND"))
    q1 = footprint("Q1", 50, 10, nets=("Q_ONLY", "GND"))
    g, cell = _cell(u1, r1, u2, r2, q1)
    text = splits.cell_text(g, cell, plane_nets={"GND"}, min_group=2)
    assert text == (
        "its parts form 2 groups joined only by board-level nets: U1, R1; U2, R2 "
        "(and 1 part no net inside the cell joins to the others: Q1, "
        "each placed by the pin it serves or the part it senses, not a split candidate). "
        "Parts with no close placement requirement in common may be split into modules of their own.")


def test_report_lists_only_the_cells_that_are_findings():
    u1 = footprint("U1", 10, 10, nets=("L1", "GND"))
    r1 = footprint("R1", 10, 20, nets=("L1", "GND"))
    u2 = footprint("U2", 30, 10, nets=("L2", "GND"))
    r2 = footprint("R2", 30, 20, nets=("L2", "GND"))
    g, split_cell = _cell(u1, r1, u2, r2)
    plain = footprint("U1", 10, 10, nets=("A", "B"))    # a second, unrelated cell with one group only
    g2 = board_geometry([dataclasses.replace(plain, cell="k")], cells=["k"], width=40.0, height=40.0)
    out = splits.report(g, [split_cell], plane_nets={"GND"}, min_group=2)
    assert [name for name, _ in out] == ["m"]
    assert splits.report(g2, [g2.cells["k"]], plane_nets=set(), min_group=2) == []
