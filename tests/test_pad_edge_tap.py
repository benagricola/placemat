"""A track point on a pad's edge, touching it: PadRef(..., edge=, along=).
For a sense track that must meet its pad at one chosen edge (a shunt's
inner edge) and nowhere else."""
import pytest

from placemat.values import Along, Edge, Part, PadRef


def test_along_without_an_edge_is_refused():
    with pytest.raises(TypeError):
        PadRef(Part("r1"), 1, along=Along.END)


def test_an_edge_is_an_edge_and_along_is_an_along():
    with pytest.raises(TypeError):
        PadRef(Part("r1"), 1, edge="south")
    with pytest.raises(TypeError):
        PadRef(Part("r1"), 1, edge=Edge.SOUTH, along="end")


def test_a_plain_padref_digests_as_before():
    from placemat.reuse import canonical
    text = str(canonical(PadRef(Part("r1"), 1)))
    assert "edge" not in text and "along" not in text


def test_offset_and_local_keep_the_edge():
    p = PadRef(Part("r1"), 1, edge=Edge.SOUTH, along=Along.END)
    for q in (p.offset(0.1, 0.0), p.local(0.0, 0.1)):
        assert q.edge is Edge.SOUTH and q.along is Along.END
