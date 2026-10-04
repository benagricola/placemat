"""Random boards with an item to scan, for the tests that compare one way of judging a scan with another
(tests/test_scan_order.py): parts, a cell of several, carried vias that may give way,
reservations, courtyards or what parts draw."""
import random
from dataclasses import replace

from placemat import giveway
from placemat.geometry import via_ring
from placemat.occupancy import Occupancy, Shape, hole_shape
from placemat.placement import Placement
from placemat.settings import Settings
from placemat.values import Box, CopperLayer, Face, Location
from tests.fixtures import board_geometry, footprint

_F, _B = CopperLayer.F, CopperLayer.B
_BOTH = frozenset([Face.FRONT, Face.BACK])


def _part(rnd, ref, x, y, envelope, nets, cell=None, through=False):
    w, h = rnd.choice([1.2, 2.0, 3.0, 4.0]), rnd.choice([0.8, 1.0, 1.6, 2.4])
    kw = {}
    if envelope != "courtyard":
        kw = dict(silk=(rnd.uniform(0, 0.3), rnd.uniform(0, 0.3), rnd.uniform(0, 0.3), rnd.uniform(0, 0.3)),
                  fab=(x - w / 2, y - h / 2, x + w / 2, y + h / 2), mask_grow=rnd.choice([None, 0.05]))
    return footprint(ref, x, y, w=w, h=h, nets=nets, cell=cell, inst=ref.lower(), through=through,
                     rotation=rnd.choice([0.0, 0.0, 90.0]), excess=rnd.choice([0.1, 0.25, 0.5]),
                     courtyard_margin=rnd.choice([0.0, 0.0, 0.05]), **kw)


def scene(rnd: random.Random, envelope: str = "courtyard", cell: bool = False, vias: bool = False, reserve: bool = False,
          settings: Settings | None = None, parts: int | None = None, ties: bool = False):
    """(occupancy, the item to scan, its hint, the rotations to try). The item is a part, or with `cell` a cell
    of a few; `vias` puts carried vias on the board, as a placed cell's, so a scan may let them give way; `reserve`
    some reservations; `ties` makes one of the parts a net tie, whose pairs the native judge leaves to Python. The item
    stands off by itself where the generator left it, pending."""
    width, height = rnd.choice([30.0, 40.0, 50.0]), rnd.choice([30.0, 40.0])
    nets = ("A", "B", "C", "D")
    fps = []
    count = rnd.randint(6, 16) if parts is None else parts
    for k in range(count):
        fps.append(_part(rnd, "P%d" % k, rnd.uniform(3, width - 3), rnd.uniform(3, height - 3), envelope,
                         (rnd.choice(nets), rnd.choice(nets)), through=rnd.random() < 0.15))
    if ties:
        k = rnd.randrange(len(fps))
        fps[k] = replace(fps[k], net_tie_pads=frozenset(["1"]))
    members = []
    if cell:
        cx, cy = rnd.uniform(5, width - 5), rnd.uniform(5, height - 5)
        for k in range(rnd.randint(2, 6)):
            members.append(_part(rnd, "M%d" % k, cx + rnd.uniform(-3, 3), cy + rnd.uniform(-3, 3), envelope,
                                 (rnd.choice(nets), rnd.choice(nets)), cell="k"))
        item_fps = members
    else:
        item_fps = [_part(rnd, "X", rnd.uniform(5, width - 5), rnd.uniform(5, height - 5), envelope, ("A", "B"))]
    g = board_geometry(fps + item_fps, cells=("k",) if cell else (), width=width, height=height, extra_nets=nets,
                       clearance=rnd.choice([0.15, 0.2, 0.3]), silk_clearance=0.2 if envelope != "courtyard" else 0.0)
    settings = settings or Settings()
    settings = replace(settings, place_envelope=envelope)
    occ = Occupancy(g, edge_margin=rnd.choice([0.3, 0.5]), settings=settings,
                    component_spacing=rnd.choice([0.0, 0.2]) if envelope != "courtyard" else 0.0)
    for fp in fps:
        occ.commit(fp, Placement(fp.location, fp.rotation, fp.face))
    item = g.cells["k"] if cell else item_fps[0]
    occ.pending |= occ._geometry(item).owners
    if vias:
        shapes = []
        for k in range(rnd.randint(1, 4)):
            x, y = rnd.uniform(3, width - 3), rnd.uniform(3, height - 3)
            size = rnd.choice([0.45, 0.6, 0.8])
            poly = via_ring(Location(x, y), size)
            shapes.append(Shape("viacell", "through", _BOTH, frozenset([_F, _B]), "A", poly, Box.of_points(poly),
                                carried="v%d" % k, points=((x, y),)))
            shapes.append(replace(hole_shape("viacell", Location(x, y), size / 2.0, "A"), carried="v%d" % k))
        occ.add_copper(shapes)
    if reserve:
        for _ in range(rnd.randint(1, 3)):
            x, y = rnd.uniform(0, width - 4), rnd.uniform(0, height - 4)
            if rnd.random() < 0.5:
                occ.reserve(Box(x, y, x + rnd.uniform(2, 8), y + rnd.uniform(2, 8)), "a keepout")
            else:
                r = rnd.uniform(2, 5)
                occ.reserve(((x, y), (x + r, y), (x + 1.4 * r, y + r), (x + r, y + 2 * r), (x, y + 1.5 * r)), "a region")
    hint = Placement(Location(rnd.uniform(5, width - 5), rnd.uniform(5, height - 5)), 0.0, Face.FRONT)
    rots = rnd.choice([(0.0,), (0.0, 90.0), (0.0, 90.0, 180.0, 270.0)])
    return occ, item, hint, rots


def carried_vias_reachable(occ, item, hint, radius) -> bool:
    """Whether a scan of `item` round `hint` would let vias give way."""
    geom = occ._geometry(item)
    region = Box(hint.location.x - radius - 10, hint.location.y - radius - 10, hint.location.x + radius + 10,
                 hint.location.y + radius + 10)
    return giveway.for_scan(occ, item, Face.FRONT, (0.0,), region, None, True) is not None
