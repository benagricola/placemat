"""Copper declarations gained new optional forms (Between, Past, bend=,
width=PadRef(...), along=/count=, stitch()) alongside the old ones. A
script that uses none of them must still digest exactly as the release
before this one did, or a lock or a reuse record it wrote stops matching
for no reason the script can see.

`plan` is a closure, and reuse.canonical() reduces every closure to the
bare string "function()" (kind()/canonical.py): the new keyword's own
resolution logic, argument-checked at declaration time, never enters a
digest, old or new. What DOES enter a digest - `refs`, `owners`, `why`,
`index`, `bridge`, `priority` - is unchanged for a call that never
mentions a new argument. The strings below were captured from the commit
this batch of relations started on (4f00cd8), before any of the new forms
existed."""
from placemat import reuse
from placemat.layout import Board
from placemat.values import CopperLayer, Location, Net, PadRef, Part, Priority
from tests.fixtures import board_geometry, footprint

ACCEPTED_BEFORE_THIS_BATCH = {
    "track": "CopperIntent(key='track A',net='A',priority=<Priority.HIGH: 'high'>,plan=function(),"
             "refs=[PadRef(part=Part(inst='u1'),key='A',dx=0.0,dy=0.0,pin=None),"
             "PadRef(part=Part(inst='u2'),key='A',dx=0.0,dy=0.0,pin=None)],why='bus',index=0,bridge=True,"
             "owners={'U1','U2'},freedom=<Freedom.FIXED: 'fixed'>)",
    "via": "CopperIntent(key='via A',net='A',priority=<Priority.DEFAULT: 'default'>,plan=function(),"
           "refs=[],why='tap',index=1,bridge=False,owners={},freedom=<Freedom.FIXED: 'fixed'>)",
    "vias": "CopperIntent(key='vias A',net='A',priority=<Priority.DEFAULT: 'default'>,plan=function(),"
            "refs=[PadRef(part=Part(inst='u1'),key='A',dx=0.0,dy=0.0,pin=None)],why='',index=2,bridge=False,"
            "owners={'U1'},freedom=<Freedom.FIXED: 'fixed'>)",
    "pour": "CopperIntent(key='pour B',net='B',priority=<Priority.DEFAULT: 'default'>,plan=function(),"
            "refs=[],why='plane',index=3,bridge=False,owners={},freedom=<Freedom.FIXED: 'fixed'>)",
    "finger": "CopperIntent(key='finger B',net='B',priority=<Priority.DEFAULT: 'default'>,plan=function(),"
              "refs=[],why='',index=4,bridge=False,owners={},freedom=<Freedom.FIXED: 'fixed'>)",
}


def _build():
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("A", "B")),
           footprint("U2", 30, 20, w=4, h=2, inst="u2", nets=("A", "B"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("u2"), at=Location(30, 20))
    items = {}
    items["track"] = b.track(Net("A"), [PadRef(Part("u1"), "A"), PadRef(Part("u2"), "A")], layer=CopperLayer.F,
                             width=0.25, chamfer=0.5, priority=Priority.HIGH, bridge=True, why="bus")
    items["via"] = b.via(Net("A"), Location(25, 25), why="tap")
    items["vias"] = b.vias(Net("A"), PadRef(Part("u1"), "A"), pitch=0.6, size=0.5, drill=0.25, inset=0.05)
    items["pour"] = b.pour(Net("B"), [Location(0, 0), Location(10, 0), Location(10, 4), Location(0, 4)],
                           layer=CopperLayer.F, why="plane")
    items["finger"] = b.finger(Net("B"), layer=CopperLayer.F, from_=(5.0, 5.0), to=(15.0, 5.0), width=1.2)
    return items


def test_old_style_copper_declarations_digest_exactly_as_before_this_batch():
    items = _build()
    digests = {key: reuse.canonical(ci) for key, ci in items.items()}
    assert digests == ACCEPTED_BEFORE_THIS_BATCH
