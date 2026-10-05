"""Removes the router's dangling copper from a routed copy, as KiCad's
TRACKS_CLEANER does (pcbnew/tracks_cleaner.cpp, KiCad 10.0).

The router leaves short tails KiCad reports as track_dangling: a segment
whose ends both land on one other item of its net - the net's filled copper
polygon, or the body of another track - and on nothing else. KiCad counts
such an item once, for the nearer end (connectivity_data.cpp:824-879,
TestTrackEndpointDangling), so the segment dangles. Zones are the exception
there (a segment wholly in a zone is "redundant, but not dangling"); copper
polygons and tracks are not.

`remove_dangling_router_copper` ports two of the cleaner's passes, in its
order (TRACKS_CLEANER::CleanupBoard):
  * deleteDanglingTracks (tracks_cleaner.cpp:275): delete every track and
    via TestTrackEndpointDangling calls dangling, marking each deleted so the
    rest of the pass sees it gone, and repeat until a pass deletes nothing;
  * then, only when something was deleted, the collinear merge of cleanup()
    (tracks_cleaner.cpp:528-650, testMergeCollinearSegments :680-777).

Deliberate divergences from the cleaner:
  * The cleaner's filter (filterItem) is "the copper the router added": the
    tracks and vias of the routed copy that the board the router was given
    does not have. Script-declared copper, escape stubs and a module's or
    cell's own copper are all on that board, so none of it is touched.
  * The cleaner skips locked items. placemat locks the island stages'
    tracks itself (route.py lock_copper) to keep the main pass off them;
    that lock does not make them declared copper, so the router's copper is
    taken whether locked or not. A merge joins two pieces only when both
    are locked or both are not.
  * The cleaner does not check what a deletion does to connectivity. Here
    the removal is kept only if the board's unconnected count did not rise;
    otherwise the copy is left as the router wrote it and the result says
    it was refused.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class Cleanup:
    """What the cleanup took off a routed copy, per net: `tracks` and `vias`
    deleted as dangling, `merged` collinear joints merged (one segment fewer
    each). `refused` is set when removing the dangling copper would have
    raised the unconnected count (`unconnected` = (before, with it removed));
    the copy is then left as the router wrote it, and the counts say what
    was found."""
    tracks: dict = field(default_factory=dict)
    vias: dict = field(default_factory=dict)
    merged: dict = field(default_factory=dict)
    refused: bool = False
    unconnected: tuple = (0, 0)

    @property
    def removed(self) -> int:
        return sum(self.tracks.values()) + sum(self.vias.values())

    def record(self) -> dict:
        return {"tracks": dict(self.tracks), "vias": dict(self.vias), "merged": dict(self.merged),
                "refused": self.refused, "unconnected": list(self.unconnected)}

    @classmethod
    def from_record(cls, d: dict) -> "Cleanup":
        return cls(dict(d.get("tracks") or {}), dict(d.get("vias") or {}), dict(d.get("merged") or {}),
                   bool(d.get("refused")), tuple(d.get("unconnected") or (0, 0)))


def _key(t) -> tuple:
    """A track's or via's identity across two boards: its kind, net, layers and geometry, to the nanometre."""
    if t.GetClass() == "PCB_VIA":
        p = t.GetPosition()
        return ("via", t.GetNetname(), p.x, p.y, t.GetWidth(t.TopLayer()), t.GetDrillValue(), t.TopLayer(), t.BottomLayer())
    a, b = (t.GetStart().x, t.GetStart().y), (t.GetEnd().x, t.GetEnd().y)
    return (t.GetClass(), t.GetNetname(), t.GetLayer(), min(a, b), max(a, b), t.GetWidth())


def router_copper(board, given) -> set:
    """The uuids of the tracks and vias on `board` that `given` (the board
    the router was given) does not have."""
    left = Counter(_key(t) for t in given.GetTracks())
    added = set()
    for t in board.GetTracks():
        k = _key(t)
        if left[k]:
            left[k] -= 1
        else:
            added.add(t.m_Uuid.AsString())
    return added


def _unconnected(board) -> int:
    board.BuildConnectivity()
    cn = board.GetConnectivity()
    cn.RecalculateRatsnest()
    return cn.GetUnconnectedCount(False)


def delete_dangling(board, mine: set, pcbnew) -> tuple:
    """TRACKS_CLEANER::deleteDanglingTracks (tracks_cleaner.cpp:275-332),
    tracks and vias, over the items whose uuid is in `mine`. Returns
    ({net: tracks deleted}, {net: vias deleted})."""
    tracks, vias = Counter(), Counter()
    while True:
        board.BuildConnectivity()
        cn = board.GetConnectivity()
        gone = []
        for t in list(board.GetTracks()):
            if t.HasFlag(pcbnew.IS_DELETED) or t.m_Uuid.AsString() not in mine:
                continue
            if cn.TestTrackEndpointDangling(t, False):
                t.SetFlags(pcbnew.IS_DELETED)      # the rest of the pass sees it gone (connectivity_data.cpp:840)
                gone.append(t)
        for t in gone:
            (vias if t.GetClass() == "PCB_VIA" else tracks)[t.GetNetname()] += 1
            board.Delete(t)
        if not gone:
            return dict(tracks), dict(vias)


def _on_ends(track, p) -> bool:
    return track.IsPointOnEnds(p)


def _merge_points(seg1, seg2, cn, pcbnew) -> int | None:
    """testMergeCollinearSegments' first half (tracks_cleaner.cpp:680-745):
    the bit set of seg1/seg2 ends another item of the net touches, or None
    when more than two do (a node in the middle)."""
    pts = (seg1.GetStart(), seg1.GetEnd(), seg2.GetStart(), seg2.GetEnd())
    flags = 0
    ids = {seg1.m_Uuid.AsString(), seg2.m_Uuid.AsString()}
    for base, seg in ((0, seg1), (2, seg2)):
        for item in cn.GetConnectedItems(seg):
            if bin(flags).count("1") > 2:
                break
            item = item.Cast()
            if item.HasFlag(pcbnew.IS_DELETED) or item.m_Uuid.AsString() in ids:
                continue
            if item.GetClass() in ("PCB_TRACK", "PCB_ARC", "PCB_VIA"):
                if item.IsPointOnEnds(pts[base]):
                    flags |= 1 << base
                if item.IsPointOnEnds(pts[base + 1]):
                    flags |= 1 << (base + 1)
            else:
                acc = (seg.GetWidth() + 1) // 2
                if not flags & (1 << base) and item.HitTest(pts[base], acc):
                    flags |= 1 << base
                if not flags & (1 << (base + 1)) and item.HitTest(pts[base + 1], acc):
                    flags |= 1 << (base + 1)
    return None if bin(flags).count("1") > 2 else flags


def _merged_ends(seg1, seg2, pcbnew) -> tuple:
    """The ends of the merged segment (tracks_cleaner.cpp:751-769)."""
    xs = [p.x for p in (seg1.GetStart(), seg1.GetEnd(), seg2.GetStart(), seg2.GetEnd())]
    ys = [p.y for p in (seg1.GetStart(), seg1.GetEnd(), seg2.GetStart(), seg2.GetEnd())]
    if (seg1.GetStart().x > seg1.GetEnd().x) == (seg1.GetStart().y > seg1.GetEnd().y):
        return pcbnew.VECTOR2I(min(xs), min(ys)), pcbnew.VECTOR2I(max(xs), max(ys))
    return pcbnew.VECTOR2I(min(xs), max(ys)), pcbnew.VECTOR2I(max(xs), min(ys))


def _test_merge(seg1, seg2, cn, pcbnew):
    """testMergeCollinearSegments (tracks_cleaner.cpp:680-777): the merged
    segment's ends, or None when the two may not merge."""
    if seg1.IsLocked() != seg2.IsLocked():     # diverges: the cleaner refuses any locked piece (see the module note)
        return None
    flags = _merge_points(seg1, seg2, cn, pcbnew)
    if flags is None:
        return None
    start, end = _merged_ends(seg1, seg2, pcbnew)
    dummy = pcbnew.PCB_TRACK(seg1)
    dummy.SetStart(start)
    dummy.SetEnd(end)
    pts = (seg1.GetStart(), seg1.GetEnd(), seg2.GetStart(), seg2.GetEnd())
    if any(flags & (1 << i) and not dummy.IsPointOnEnds(pts[i]) for i in range(4)):
        return None
    # testTrackEndpointIsNode (tracks_cleaner.cpp:234-272) asks only when both of seg1's ends stay ends, and then
    # counts the items with one anchor on both of them: for a segment of non-zero length, none. Not a node.
    return start, end


def merge_collinear(board, mine: set, pcbnew) -> dict:
    """The collinear merge of TRACKS_CLEANER::cleanup (tracks_cleaner.cpp:528-650)
    over the segments whose uuid is in `mine`, repeated until a pass finds no
    pair. Returns {net: joints merged}."""
    merged = Counter()
    while True:
        board.BuildConnectivity()
        cn = board.GetConnectivity()
        cn.RecalculateRatsnest()                  # links the items (tracks_cleaner.cpp:638-641)
        pairs = []
        for seg in list(board.GetTracks()):
            if seg.GetClass() != "PCB_TRACK" or seg.HasFlag(pcbnew.IS_DELETED) or seg.m_Uuid.AsString() not in mine:
                continue
            same, other = [], False
            for c in cn.GetConnectedTracks(seg):
                c = c.Cast()
                if c.GetClass() != "PCB_TRACK" or c.HasFlag(pcbnew.IS_DELETED) or c.m_Uuid.AsString() not in mine:
                    continue
                if c.GetWidth() == seg.GetWidth():
                    same.append(c)
                else:
                    other = True                   # a neck between widths is kept (tracks_cleaner.cpp:560-563)
                    break
            if other:
                continue
            for c in same:
                if c.m_Uuid.AsString() <= seg.m_Uuid.AsString() or c.m_Uuid.AsString() == seg.m_Uuid.AsString():
                    continue
                if seg.ApproxCollinear(c) and _test_merge(seg, c, cn, pcbnew) is not None:
                    pairs.append((seg, c))
                    break
        done = 0
        for seg1, seg2 in pairs:
            if seg1.HasFlag(pcbnew.IS_DELETED) or seg2.HasFlag(pcbnew.IS_DELETED):
                continue
            ends = _test_merge(seg1, seg2, cn, pcbnew)
            if ends is None:
                continue
            seg1.SetStart(ends[0])
            seg1.SetEnd(ends[1])
            seg2.SetFlags(pcbnew.IS_DELETED)
            merged[seg1.GetNetname()] += 1
            done += 1
        for seg in [t for t in board.GetTracks() if t.HasFlag(pcbnew.IS_DELETED)]:
            board.Delete(seg)
        if not done:
            return dict(merged)


def remove_dangling_router_copper(pcb_path: str, given_path: str) -> Cleanup:
    """Delete the router's dangling tracks and vias from the routed copy at
    `pcb_path`, repeating as each deletion can leave another dangling, then
    merge the router's collinear pieces the deletions leave meeting, and
    save. `given_path` is the board the router was given: its copper is
    never touched. Zones are expected filled (KiCad tests a track end in a
    zone against its fill)."""
    from .quiet import import_pcbnew, quiet_stderr
    pcbnew = import_pcbnew()
    with quiet_stderr():
        board = pcbnew.LoadBoard(pcb_path)
        given = pcbnew.LoadBoard(given_path)
    mine = router_copper(board, given)
    if not mine:
        return Cleanup()
    before = _unconnected(board)
    tracks, vias = delete_dangling(board, mine, pcbnew)
    if not (tracks or vias):
        return Cleanup(unconnected=(before, before))
    after = _unconnected(board)
    if after > before:
        return Cleanup(tracks, vias, {}, True, (before, after))
    live = {t.m_Uuid.AsString() for t in board.GetTracks()} & mine
    merged = merge_collinear(board, live, pcbnew)
    after = _unconnected(board)
    with quiet_stderr():
        board.Save(pcb_path)
    return Cleanup(tracks, vias, merged, False, (before, after))
