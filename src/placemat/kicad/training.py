"""A routed run's training record: the placed board as a raster and what the route made of each net, for a model that
learns from routed runs which placements route.

The record is two files in the route's work folder. TRAINING_JSON holds the raster's frame, its channel names and
each net's outcome; TRAINING_RASTER holds the channels, uint8 cells, channel by channel and row by row, zlib
compressed. A channel is a mask (0 or 255) of the input board:
- "board": inside the board outline (every cell of a board with none, framed by its items);
- "pad:<layer>" and "track:<layer>" for each copper layer: a pad's bounding box on that layer, a track's copper;
- "hole": a pad's or via's hole;
- "keepout": a rule area that forbids tracks;
- "rudy": each net's wiring demand, the RUDY estimate (half-perimeter over area of its pads' box), scaled so that
  the busiest cell is 255.
"""
from __future__ import annotations

import json
import math
import zlib
from pathlib import Path

TRAINING_JSON = "training.json"
TRAINING_RASTER = "training.raster"
FORMAT = 1


class Raster:
    """uint8 channels over the board's outline box, `cell_mm` a cell."""

    def __init__(self, x0: float, y0: float, x1: float, y1: float, cell_mm: float):
        self.x0, self.y0, self.cell = x0, y0, cell_mm
        self.width = max(1, int(math.ceil((x1 - x0) / cell_mm)))
        self.height = max(1, int(math.ceil((y1 - y0) / cell_mm)))
        self.channels: dict = {}

    def channel(self, name: str) -> bytearray:
        if name not in self.channels:
            self.channels[name] = bytearray(self.width * self.height)
        return self.channels[name]

    def cells(self, x0: float, y0: float, x1: float, y1: float):
        """The (column, row) of each cell whose centre lies in the box, clipped to the raster."""
        c0 = max(0, int(math.ceil((x0 - self.x0) / self.cell - 0.5)))
        c1 = min(self.width - 1, int(math.floor((x1 - self.x0) / self.cell - 0.5)))
        r0 = max(0, int(math.ceil((y0 - self.y0) / self.cell - 0.5)))
        r1 = min(self.height - 1, int(math.floor((y1 - self.y0) / self.cell - 0.5)))
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                yield c, r

    def centre(self, c: int, r: int) -> tuple:
        return self.x0 + (c + 0.5) * self.cell, self.y0 + (r + 0.5) * self.cell

    def fill_box(self, name: str, x0: float, y0: float, x1: float, y1: float) -> None:
        ch = self.channel(name)
        for c, r in self.cells(x0, y0, x1, y1):
            ch[r * self.width + c] = 255

    def fill_segment(self, name: str, ax: float, ay: float, bx: float, by: float, half: float) -> None:
        ch = self.channel(name)
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        for c, r in self.cells(min(ax, bx) - half, min(ay, by) - half, max(ax, bx) + half, max(ay, by) + half):
            px, py = self.centre(c, r)
            t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
            if math.hypot(ax + t * dx - px, ay + t * dy - py) <= half:
                ch[r * self.width + c] = 255

    def data(self, names) -> bytes:
        return zlib.compress(b"".join(bytes(self.channel(n)) for n in names), 6)


def rudy(raster: Raster, nets: dict) -> None:
    """The "rudy" channel from {net: [(x, y) pad centre, ...]}: each net of two pads or more adds its half-perimeter
    over area (a box at least one cell wide each way) to the cells of its pads' box."""
    demand = [0.0] * (raster.width * raster.height)
    for points in nets.values():
        if len(points) < 2:
            continue
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        w, h = max(max(xs) - min(xs), raster.cell), max(max(ys) - min(ys), raster.cell)
        add = (w + h) / (w * h)
        for c, r in raster.cells(min(xs), min(ys), max(xs), max(ys)):
            demand[r * raster.width + c] += add
    top = max(demand) or 1.0
    ch = raster.channel("rudy")
    for i, v in enumerate(demand):
        ch[i] = int(round(255 * v / top))


def board_raster(board, pcbnew, cell_mm: float) -> tuple:
    """(raster, channel names, {net: [(x, y) pad centre, ...]}) of a loaded pcbnew board."""
    mm = pcbnew.ToMM
    box = board.GetBoardEdgesBoundingBox()
    if box.GetWidth() <= 0 or box.GetHeight() <= 0:
        box = board.ComputeBoundingBox(False)       # no outline (a module's board): the box of its items
    raster = Raster(mm(box.GetLeft()), mm(box.GetTop()), mm(box.GetRight()), mm(box.GetBottom()), cell_mm)
    outline = pcbnew.SHAPE_POLY_SET()
    has_outline = board.GetBoardPolygonOutlines(outline, False)
    ch = raster.channel("board")
    for r in range(raster.height):
        for c in range(raster.width):
            x, y = raster.centre(c, r)
            if not has_outline or outline.Contains(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))):
                ch[r * raster.width + c] = 255
    layers = [(l, board.GetLayerName(l)) for l in board.GetEnabledLayers().CuStack()]
    names = ["board"] + ["pad:" + n for _, n in layers] + ["track:" + n for _, n in layers] + ["hole", "keepout", "rudy"]
    for n in names:
        raster.channel(n)
    nets: dict = {}
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            b = pad.GetBoundingBox()
            x0, y0, x1, y1 = mm(b.GetLeft()), mm(b.GetTop()), mm(b.GetRight()), mm(b.GetBottom())
            for layer, name in layers:
                if pad.IsOnLayer(layer):
                    raster.fill_box("pad:" + name, x0, y0, x1, y1)
            drill = pad.GetDrillSize()
            if drill.x > 0:
                p, half = pad.GetPosition(), mm(min(drill.x, drill.y)) / 2.0
                raster.fill_segment("hole", mm(p.x), mm(p.y), mm(p.x), mm(p.y), half)
            if pad.GetNetname():
                p = pad.GetPosition()
                nets.setdefault(pad.GetNetname(), []).append((round(mm(p.x), 4), round(mm(p.y), 4)))
    for t in board.GetTracks():
        if isinstance(t, pcbnew.PCB_VIA):
            p = t.GetPosition()
            for layer, name in layers:
                if t.IsOnLayer(layer):
                    raster.fill_segment("track:" + name, mm(p.x), mm(p.y), mm(p.x), mm(p.y), mm(t.GetWidth(layer)) / 2.0)
            raster.fill_segment("hole", mm(p.x), mm(p.y), mm(p.x), mm(p.y), mm(t.GetDrillValue()) / 2.0)
            continue
        name = board.GetLayerName(t.GetLayer())
        if "track:" + name in raster.channels:
            a, b = t.GetStart(), t.GetEnd()
            raster.fill_segment("track:" + name, mm(a.x), mm(a.y), mm(b.x), mm(b.y), mm(t.GetWidth()) / 2.0)
    keep = raster.channel("keepout")
    for z in board.Zones():
        if not (z.GetIsRuleArea() and z.GetDoNotAllowTracks()):
            continue
        b = z.GetBoundingBox()
        for c, r in raster.cells(mm(b.GetLeft()), mm(b.GetTop()), mm(b.GetRight()), mm(b.GetBottom())):
            x, y = raster.centre(c, r)
            if z.Outline().Contains(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))):
                keep[r * raster.width + c] = 255
    rudy(raster, nets)
    return raster, names, nets


def net_copper(board, pcbnew) -> dict:
    """{net: {"track_mm", "vias"}} of a loaded board's tracks and vias."""
    out: dict = {}
    for t in board.GetTracks():
        n = t.GetNetname()
        if not n:
            continue
        rec = out.setdefault(n, {"track_mm": 0.0, "vias": 0})
        if isinstance(t, pcbnew.PCB_VIA):
            rec["vias"] += 1
        else:
            rec["track_mm"] += pcbnew.ToMM(t.GetLength())
    return out


def write_record(pcb_in, pcb_out, work, open_before: dict, open_after: dict, facts: dict, cell_mm: float) -> Path:
    """Write the training record of a route from `pcb_in` (the placed board) to `pcb_out` into `work`, and return
    the TRAINING_JSON path. `open_before` and `open_after` are {net: open items} before and after the route; `facts`
    goes into the record as it is (closure, versions, layers, seconds). A net's `track_mm` and `vias` are the copper
    the route added to it."""
    from .quiet import import_pcbnew, quiet_stderr
    pcbnew = import_pcbnew()
    with quiet_stderr():
        board_in = pcbnew.LoadBoard(str(pcb_in))
        board_out = pcbnew.LoadBoard(str(pcb_out))
    raster, names, pads = board_raster(board_in, pcbnew, cell_mm)
    before, after = net_copper(board_in, pcbnew), net_copper(board_out, pcbnew)
    nets = {}
    for n in sorted(set(pads) | set(open_before) | set(open_after)):
        b, a = before.get(n, {"track_mm": 0.0, "vias": 0}), after.get(n, {"track_mm": 0.0, "vias": 0})
        nets[n] = {"pads": pads.get(n, []), "open_before": open_before.get(n, 0), "open_after": open_after.get(n, 0),
                   "track_mm": round(a["track_mm"] - b["track_mm"], 3), "vias": a["vias"] - b["vias"]}
    work = Path(work)
    (work / TRAINING_RASTER).write_bytes(raster.data(names))
    record = dict(facts, format=FORMAT, cell_mm=cell_mm, origin_mm=[raster.x0, raster.y0],
                  width=raster.width, height=raster.height, channels=names, raster=TRAINING_RASTER, nets=nets)
    path = work / TRAINING_JSON
    path.write_text(json.dumps(record, sort_keys=True) + "\n")
    return path


def read_raster(json_path) -> tuple:
    """(record, {channel: bytes}) of a written training record."""
    json_path = Path(json_path)
    record = json.loads(json_path.read_text())
    data = zlib.decompress((json_path.parent / record["raster"]).read_bytes())
    size = record["width"] * record["height"]
    return record, {n: data[i * size:(i + 1) * size] for i, n in enumerate(record["channels"])}
