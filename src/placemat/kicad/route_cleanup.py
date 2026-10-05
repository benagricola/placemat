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
  * The cleaner's filter (filterItem) is "the copper the router added". The
    copper the router was given is never touched (`given_copper`): an item
    whose uuid is on the board the router was given (the router keeps the
    uuids of what it was given), one matching a given item's geometry, and
    a segment lying on a given track of its net and layer (the router
    writing a given track again in pieces). Script-declared copper, escape
    stubs and a module's or cell's own copper are all given.
  * The cleaner skips locked items. The given copper is locked (route.py
    lock_copper), and stays protected as above. placemat also locks the
    island stages' router copper to keep the main pass off it; that lock
    does not make it given, so it is taken. A merge joins two pieces only
    when both are locked or both are not.
  * A net whose pads are not all joined in the routed copy (`pad_groups`)
    keeps its router copper, dangling or not: the router keeps a failed
    net's copper on purpose (KRT cleanup_pipeline.py, protected nets, #473),
    as progress a later route or a hand builds on. Named in `kept_unrouted`.
  * The cleaner does not check what a deletion does to connectivity. KiCad
    calls a segment dangling when another of its net lands on its body short
    of its end, so deleting it can part the net's pads. Here a net whose
    pads fall into more groups once its dangling copper is deleted keeps all
    its router copper as the router wrote it, and is named in
    `refused_nets`; the other nets are cleaned.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

LIE_ON_NM = 1000       # a router segment whose ends are within this of a given track's centreline lies on it (1 um)


@dataclass
class Cleanup:
    """What the cleanup took off a routed copy, per net: `tracks` and `vias`
    deleted as dangling, `merged` collinear joints merged (one segment fewer
    each). `unconnected` is the board's unconnected count (before, after).
    `kept_unrouted` names the nets left unconnected whose dangling router
    copper was kept; `refused_nets` the nets whose pads the dangling router
    copper alone joined, which keep it."""
    tracks: dict = field(default_factory=dict)
    vias: dict = field(default_factory=dict)
    merged: dict = field(default_factory=dict)
    unconnected: tuple = (0, 0)
    kept_unrouted: list = field(default_factory=list)
    refused_nets: list = field(default_factory=list)

    def record(self) -> dict:
        return {"tracks": dict(self.tracks), "vias": dict(self.vias), "merged": dict(self.merged),
                "unconnected": list(self.unconnected), "kept_unrouted": list(self.kept_unrouted),
                "refused_nets": list(self.refused_nets)}


def _key(t) -> tuple:
    """A track's or via's identity across two boards: its kind, net, layers and geometry, to the nanometre."""
    if t.GetClass() == "PCB_VIA":
        p = t.GetPosition()
        return ("via", t.GetNetname(), p.x, p.y, t.GetWidth(t.TopLayer()), t.GetDrillValue(), t.TopLayer(), t.BottomLayer())
    a, b = (t.GetStart().x, t.GetStart().y), (t.GetEnd().x, t.GetEnd().y)
    return (t.GetClass(), t.GetNetname(), t.GetLayer(), min(a, b), max(a, b), t.GetWidth())


def _off_line(p, a, b) -> float:
    """The distance from point p to segment a-b, in nm."""
    ax, ay, bx, by, px, py = a.x, a.y, b.x, b.y, p.x, p.y
    dx, dy = bx - ax, by - ay
    n = dx * dx + dy * dy
    t = 0.0 if n == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / n))
    return ((ax + t * dx - px) ** 2 + (ay + t * dy - py) ** 2) ** 0.5


def given_copper(board, given) -> set:
    """The uuids of the tracks and vias on `board` that are the copper the
    router was given (`given`): an item with a given item's uuid or
    geometry, or a segment both of whose ends lie on a given track of its
    net and layer."""
    uuids = {t.m_Uuid.AsString() for t in given.GetTracks()}
    left = Counter(_key(t) for t in given.GetTracks())
    lines = {}
    for t in given.GetTracks():
        if t.GetClass() == "PCB_TRACK":
            lines.setdefault((t.GetNetname(), t.GetLayer()), []).append((t.GetStart(), t.GetEnd()))
    found = set()
    for t in board.GetTracks():
        u, k = t.m_Uuid.AsString(), _key(t)
        if u in uuids:
            found.add(u)
        elif left[k]:
            left[k] -= 1
            found.add(u)
        elif t.GetClass() == "PCB_TRACK" and any(
                _off_line(t.GetStart(), a, b) <= LIE_ON_NM and _off_line(t.GetEnd(), a, b) <= LIE_ON_NM
                for a, b in lines.get((t.GetNetname(), t.GetLayer()), ())):
            found.add(u)
    return found


def _unconnected(board) -> int:
    board.BuildConnectivity()
    cn = board.GetConnectivity()
    cn.RecalculateRatsnest()
    return cn.GetUnconnectedCount(False)


def pad_groups(board, pcbnew) -> dict:
    """{net: how many connected groups its pads fall into}, over the nets
    with a copper pad. This departs from DRC's unconnected count, which
    joins every copper cluster of a net, pads or not: a floating fragment
    is not a group here, so a net whose pads are all joined counts 1 with a
    fragment beside it, and the fragment is cleaned as junk. A net with a
    single pad is 1 whatever copper hangs off it. An NPTH pad has no copper
    and joins nothing, so it is left out (KiCad leaves it out of a net's
    connectivity too)."""
    board.BuildConnectivity()
    cn = board.GetConnectivity()
    pads = {}
    for p in board.GetPads():
        if p.GetNetCode() > 0 and p.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH:
            pads.setdefault(p.GetNetname(), []).append(p)
    groups = {}
    for net, ps in pads.items():
        seen, n = set(), 0
        for p in ps:
            if p.m_Uuid.AsString() in seen:
                continue
            n += 1
            seen.add(p.m_Uuid.AsString())
            seen |= {i.m_Uuid.AsString() for i in cn.GetConnectedItems(p) if i.GetClass() == "PAD"}
        groups[net] = n
    return groups


def _delete(board, item) -> None:
    group = item.GetParentGroup()
    if group is not None:
        group.RemoveItem(item)
    board.Delete(item)


def delete_dangling(board, mine: set, pcbnew, keep_nets=frozenset()) -> tuple:
    """TRACKS_CLEANER::deleteDanglingTracks (tracks_cleaner.cpp:275-332),
    tracks and vias, over the items whose uuid is in `mine`; a dangling item
    on a net in `keep_nets` stays. Returns ({net: tracks deleted}, {net: vias
    deleted}, the nets of `keep_nets` with a dangling item kept)."""
    tracks, vias, kept = Counter(), Counter(), set()
    while True:
        board.BuildConnectivity()
        cn = board.GetConnectivity()
        gone = []
        for t in list(board.GetTracks()):
            if t.HasFlag(pcbnew.IS_DELETED) or t.m_Uuid.AsString() not in mine:
                continue
            if cn.TestTrackEndpointDangling(t, False):
                if t.GetNetname() in keep_nets:
                    kept.add(t.GetNetname())
                    continue
                t.SetFlags(pcbnew.IS_DELETED)      # the rest of the pass sees it gone (connectivity_data.cpp:840)
                gone.append(t)
        for t in gone:
            (vias if t.GetClass() == "PCB_VIA" else tracks)[t.GetNetname()] += 1
            _delete(board, t)
        if not gone:
            return dict(tracks), dict(vias), kept


def _merge_points(seg1, seg2, connected, pcbnew) -> int | None:
    """testMergeCollinearSegments' first half (tracks_cleaner.cpp:680-745):
    the bit set of seg1/seg2 ends another item of the net touches, or None
    when more than two do (a node in the middle). `connected(seg)` is the
    pass's cached GetConnectedItems."""
    pts = (seg1.GetStart(), seg1.GetEnd(), seg2.GetStart(), seg2.GetEnd())
    flags = 0
    ids = {seg1.m_Uuid.AsString(), seg2.m_Uuid.AsString()}
    for base, seg in ((0, seg1), (2, seg2)):
        for item in connected(seg):
            if bin(flags).count("1") > 2:
                break
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


def _test_merge(seg1, seg2, connected, pcbnew):
    """testMergeCollinearSegments (tracks_cleaner.cpp:680-777): the merged
    segment's ends, or None when the two may not merge."""
    if seg1.IsLocked() != seg2.IsLocked():     # diverges: the cleaner refuses any locked piece (see the module note)
        return None
    flags = _merge_points(seg1, seg2, connected, pcbnew)
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
    over the segments whose uuid is in `mine`. Returns {net: joints merged}.

    Two divergences. The cleaner repeats while a pass finds a pair
    (`while( mergeSegments(...) )`, :633-650), whether or not the pair then
    merges; this repeats while a pass merges one, so a pair found but refused
    at merge time cannot repeat forever. After a merge the cleaner updates
    the connectivity for the merged segment (:798); this leaves the pass's
    connectivity as built, marks the absorbed segment deleted (which the
    tests of the rest of the pass skip, as the cleaner's do) and builds the
    connectivity again for the next pass."""
    merged = Counter()
    while True:
        board.BuildConnectivity()
        cn = board.GetConnectivity()
        cn.RecalculateRatsnest()                  # links the items (tracks_cleaner.cpp:638-641)
        cache = {}                                # the cleaner's m_connectedItemsCache, cleared each pass (:642-643, :668-676)

        def connected(seg):
            u = seg.m_Uuid.AsString()
            if u not in cache:
                cache[u] = [i.Cast() for i in cn.GetConnectedItems(seg)]
            return cache[u]

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
                if c.m_Uuid.AsString() <= seg.m_Uuid.AsString():     # each pair once (the cleaner's `candidate < segment`)
                    continue
                if seg.ApproxCollinear(c) and _test_merge(seg, c, connected, pcbnew) is not None:
                    pairs.append((seg, c))
                    break
        done = 0
        for seg1, seg2 in pairs:
            if seg1.HasFlag(pcbnew.IS_DELETED) or seg2.HasFlag(pcbnew.IS_DELETED):
                continue
            ends = _test_merge(seg1, seg2, connected, pcbnew)
            if ends is None:
                continue
            seg1.SetStart(ends[0])
            seg1.SetEnd(ends[1])
            seg2.SetFlags(pcbnew.IS_DELETED)
            merged[seg1.GetNetname()] += 1
            done += 1
        for seg in [t for t in board.GetTracks() if t.HasFlag(pcbnew.IS_DELETED)]:
            _delete(board, seg)
        if not done:
            return dict(merged)


def remove_dangling_router_copper(pcb_path: str, given_path: str) -> Cleanup:
    """Delete the router's dangling tracks and vias from the routed copy at
    `pcb_path`, repeating as each deletion can leave another dangling, then
    merge the router's collinear pieces, and save. `given_path` is the board
    the router was given: its copper is never touched. A net whose pads are
    not all joined keeps its router copper, and so does a net whose pads the
    deletion would part. Zones are expected filled (KiCad tests a track end
    in a zone against its fill)."""
    from .quiet import import_pcbnew, quiet_stderr
    pcbnew = import_pcbnew()
    with quiet_stderr():
        given = pcbnew.LoadBoard(given_path)
        board = pcbnew.LoadBoard(pcb_path)
    ours = {t.m_Uuid.AsString() for t in board.GetTracks()}
    mine = ours - given_copper(board, given)
    if not mine:
        return Cleanup()
    groups = pad_groups(board, pcbnew)
    unrouted = {n for n, g in groups.items() if g > 1}
    before = _unconnected(board)
    refused = set()
    while True:
        tracks, vias, kept = delete_dangling(board, mine, pcbnew, unrouted | refused)
        after_groups = pad_groups(board, pcbnew)
        parted = {n for n, g in after_groups.items() if g > groups.get(n, 0)}
        if not parted:
            break
        refused |= parted                 # those nets as the router wrote them: start over from the file
        with quiet_stderr():
            board = pcbnew.LoadBoard(pcb_path)
    kept_unrouted = sorted(kept & unrouted)
    if not (tracks or vias):
        return Cleanup(unconnected=(before, before), kept_unrouted=kept_unrouted, refused_nets=sorted(refused))
    live = {t.m_Uuid.AsString() for t in board.GetTracks()
            if t.GetNetname() not in unrouted | refused} & mine
    merged = merge_collinear(board, live, pcbnew)
    after = _unconnected(board)
    with quiet_stderr():
        board.Save(pcb_path)
    return Cleanup(tracks, vias, merged, (before, after), kept_unrouted, sorted(refused))
