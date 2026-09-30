"""The fab profile says which via types the fab makes, and cost allows:
micro, blind and buried vias are refused unless fab-profile.json allows them
(`"via": {"allow_micro": true, ...}`). A through via is always allowed."""
import dataclasses
import json

import pytest

from placemat.board_geometry import CopperItem
from placemat.layout import Board
from placemat.project import fab_profile
from placemat.values import Box, Cell, CopperLayer, Location, Net
from tests.fixtures import board_geometry, footprint

F, B = CopperLayer.F, CopperLayer.B
IN1, IN2, IN3, IN4 = CopperLayer.IN1, CopperLayer.IN2, CopperLayer.IN3, CopperLayer.IN4
SIX = (F, IN1, IN2, IN3, IN4, B)


def _board(**kw):
    g = dataclasses.replace(board_geometry([], width=30, height=30, extra_nets=("GND",)), layers=SIX)
    return Board(g, edge_margin=0.5, keep_going=True, **kw)


def test_a_micro_via_is_refused_when_the_fab_profile_does_not_allow_it():
    with pytest.raises(ValueError, match='"micro"'):
        _board().via(Net("GND"), Location(10, 10), layers=(B, IN4))


def test_each_type_needs_its_own_allowance():
    b = _board(fab_via_tiers={"micro": "yes"})
    b.via(Net("GND"), Location(10, 10), layers=(B, IN4))                      # micro: allowed
    with pytest.raises(ValueError, match='"blind"'):
        b.via(Net("GND"), Location(12, 10), layers=(B, IN2))                  # blind
    with pytest.raises(ValueError, match='"buried"'):
        b.via(Net("GND"), Location(14, 10), layers=(IN1, IN3))                # buried


def test_an_if_needed_via_is_refused_like_no_but_says_it_is_preferred_off():
    b = _board(fab_via_tiers={"micro": "if-needed"})
    with pytest.raises(ValueError, match="if-needed"):
        b.via(Net("GND"), Location(10, 10), layers=(B, IN4))


def test_a_through_via_needs_no_allowance():
    _board().via(Net("GND"), Location(10, 10))
    _board().via(Net("GND"), Location(10, 10), layers=(F, B))                 # every layer: through


def test_the_fab_profile_reads_the_allowances_and_keeps_its_digest_without_them(tmp_path):
    (tmp_path / "fab-profile.json").write_text(json.dumps({"via": {"allow_blind": True}}))
    fab = fab_profile(tmp_path)
    assert fab.via_types == frozenset({"blind"})
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "fab-profile.json").write_text(json.dumps({"via": {}}))
    assert "allow" not in fab_profile(plain).json()


def test_a_stamped_cell_carrying_a_blind_via_fails_the_run_unless_allowed():
    poly = ((9.8, 9.8), (10.2, 9.8), (10.2, 10.2), (9.8, 10.2))
    via = CopperItem("via", "GND", frozenset({B, IN4, IN3}), (poly,), Box.of_points(poly), "k", 0.4, 0.2,
                     anchors=((10.0, 10.0),))
    fp = footprint("U1", 10, 12, inst="k.u1", cell="k", nets=("GND", "A"))
    g = dataclasses.replace(board_geometry([fp], cells=("k",), copper=[via], width=30, height=30), layers=SIX)
    with pytest.raises(ValueError, match="cell k.*blind"):
        Board(g, edge_margin=0.5, keep_going=True).resolve()
    Board(g, edge_margin=0.5, keep_going=True, fab_via_tiers={"blind": "yes"}).resolve()
