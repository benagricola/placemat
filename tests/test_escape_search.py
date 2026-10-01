"""A searched part's escape lanes are weighed in its search: each candidate is priced score.escape_lane for
every lane that would meet another net's pad, hole or copper already placed, or whose via has no legal
spot. Where every spot is blocked the part still lands, and each blocked lane is a finding. Pure."""
import pytest

from placemat.copper import Track
from placemat.settings import Settings
from placemat.values import Edge, Location, Near, Net, Part, CopperLayer
from tests.escape_fixtures import PD_NETS, board_with, qfn
from tests.fixtures import footprint

F = CopperLayer.F


def _board(radius=1.5, **kw):
    """A searched QFN with three lanes out of its north row, hinted at (30, 30), and a part already placed
    just north of that spot whose pad would sit on the lanes there (its pad 0.1 mm off the PGOOD lane)."""
    blocker = footprint("B1", 28.6, 25.0, w=1.6, h=0.6, inst="blk", nets=("OTHER", "GND"))
    b = board_with([qfn(nets=PD_NETS), blocker], **kw)
    b.place(Part("blk"), at=Location(28.6, 25.0))
    b.place(Part("pd"), at=Near(Location(30, 30), radius=radius, step=0.5, rotations=(0.0,)))
    esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31, 30], why="north row")
    return b, esc


def _lane_findings(plan):
    return [f for f in plan.findings if f.kind == "escape_lane"]


def test_the_search_lands_where_every_lane_lies_clear():
    b, _ = _board()
    plan = b.resolve()
    where = plan.placement("pd").location
    assert (where.x, where.y) != (30.0, 30.0)                      # the nearer spot would have blocked a lane
    assert not _lane_findings(plan)
    assert not [f for f in plan.findings if f.kind in ("fixed", "unplaced")]


def test_without_the_price_the_nearest_spot_wins_and_the_blocked_lane_is_a_finding():
    b, _ = _board(settings=Settings(score_escape_lane=0.0))
    plan = b.resolve()
    where = plan.placement("pd").location
    assert (where.x, where.y) == (30.0, 30.0)
    (found,) = _lane_findings(plan)
    assert "pin 30" in found and "lane is blocked by" in found and "OTHER" in found     # names what blocks it


def test_with_every_spot_blocked_the_part_lands_and_the_blocked_lane_is_a_finding():
    b, _ = _board(radius=0.2)                                      # one candidate: the hint itself
    plan = b.resolve()
    where = plan.placement("pd").location
    assert (where.x, where.y) == (30.0, 30.0)
    (found,) = _lane_findings(plan)
    assert "pin 30" in found and "OTHER" in found
    assert plan.step("pd").placement is not None


def test_the_price_is_the_setting():
    b, _ = _board(settings=Settings(score_escape_lane=1.0))
    plan = b.resolve()
    assert (plan.placement("pd").location.x, plan.placement("pd").location.y) != (30.0, 30.0)     # still avoids it
    assert Settings().score_escape_lane == 400.0
    assert "escape_lane" in __import__("placemat.score", fromlist=["TERMS"]).TERMS


def test_the_escape_settings_load_with_their_floors(tmp_path):
    from placemat import settings as S
    (tmp_path / "placemat.toml").write_text("[score]\nescape_lane = 0\n[place]\nescape_via_step = 0.1\nescape_via_reach = 3\n")
    s = S.load(tmp_path)
    assert (s.score_escape_lane, s.place_escape_via_step, s.place_escape_via_reach) == (0, 0.1, 3)
    for text in ("[score]\nescape_lane = -1\n", "[place]\nescape_via_step = 0\n", "[place]\nescape_via_reach = 0\n"):
        (tmp_path / "placemat.toml").write_text(text)
        with pytest.raises(S.SettingsError):
            S.load(tmp_path)


def test_the_lane_finding_is_scored_like_the_other_escape_findings():
    from placemat import score
    cfg = Settings()
    m = {"findings": {"escape_lane": 2}}
    assert score.terms(m, cfg)["escape_lane"] == 2 * cfg.score_escape_lane
