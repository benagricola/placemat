"""Origin, Mid keys, Pin(land=), Parallel, Bearing and Facing are new forms. A
script that uses none of them must digest exactly as the release before
did, or a lock or a reuse record it wrote stops matching for no reason the
script can see. The strings below were captured before they existed."""
from placemat import reuse
from placemat.layout import Board
from placemat.values import Beside, Edge, Location, PadRef, Part, Pin, Polar, Turned, X
from tests.fixtures import board_geometry, footprint

ACCEPTED_BEFORE = [
    "PlaceIntent(key='u1',item=fp:U1,kind='part',priority=<Priority.DEFAULT: 'default'>,rotation=90.0,face=<Face.FRONT: 'front'>,at=Location(x=20,y=20),center=None,edge=None,along=None,clearance=1.0,near=None,radius=3.0,step=0.2,rotations=[],why='',index=0,needs={},pin_x=None,pin_y=None,priority_source='auto',faces_note='',pinned_by='',pin=None,rim=None,angle=None,radius_at=None,outward=False,about=None,run=None,freedom=<Freedom.FIXED: 'fixed'>,required=False,rotation_given=True)",
    "PlaceIntent(key='u2',item=fp:U2,kind='part',priority=<Priority.DEFAULT: 'default'>,rotation=90.0,face=<Face.FRONT: 'front'>,at=None,center=[PadRef(part=Part(inst='u1'),key=2,dx=0.0,dy=0.0,pin=None),PadRef(part=Part(inst='u1'),key=2,dx=0.0,dy=0.0,pin=None)],edge=None,along=None,clearance=1.0,near=None,radius=3.0,step=0.2,rotations=[],why='',index=1,needs={'U1'},pin_x=None,pin_y=None,priority_source='auto',faces_note='',pinned_by='',pin=1,rim=None,angle=None,radius_at=None,outward=False,about=None,run=None,freedom=<Freedom.FIXED: 'fixed'>,required=False,rotation_given=True,turned=Turned(part=Part(inst='u1'),degrees=90))",
    "PlaceIntent(key='u3',item=fp:U3,kind='part',priority=<Priority.DEFAULT: 'default'>,rotation=0.0,face=<Face.FRONT: 'front'>,at=None,center=None,edge=None,along=None,clearance=1.0,near=None,radius=3.0,step=0.2,rotations=[],why='',index=2,needs={'U1'},pin_x=None,pin_y=None,priority_source='auto',faces_note='',pinned_by='',pin=None,rim=None,angle=None,radius_at=None,outward=False,about=None,run=None,freedom=<Freedom.FIXED: 'fixed'>,required=False,rotation_given=True,beside=_BesideSpec(item=Part(inst='u1'),side=<Edge.SOUTH: 'S'>,align=['pads',1,PadRef(part=Part(inst='u1'),key=1,dx=0.0,dy=0.0,pin=None)],gap=None))",
    "PlaceIntent(key='u4',item=fp:U4,kind='part',priority=<Priority.DEFAULT: 'default'>,rotation=0.0,face=<Face.FRONT: 'front'>,at=None,center=[X(ref=PadRef(part=Part(inst='u1'),key=1,dx=0.0,dy=0.0,pin=None),dx=0.0),40.0],edge=None,along=None,clearance=1.0,near=None,radius=3.0,step=0.2,rotations=[],why='',index=3,needs={'U1'},pin_x=None,pin_y=None,priority_source='auto',faces_note='',pinned_by='',pin=2,rim=None,angle=None,radius_at=None,outward=False,about=None,run=None,freedom=<Freedom.FIXED: 'fixed'>,required=False,rotation_given=True)",
    "PlaceIntent(key='u5',item=fp:U5,kind='part',priority=<Priority.DEFAULT: 'default'>,rotation=0.0,face=<Face.FRONT: 'front'>,at=None,center=Polar(radius=5.0,angle=90.0,about=PadRef(part=Part(inst='u1'),key=1,dx=0.0,dy=0.0,pin=None)),edge=None,along=None,clearance=1.0,near=None,radius=3.0,step=0.2,rotations=[],why='',index=4,needs={'U1'},pin_x=None,pin_y=None,priority_source='auto',faces_note='',pinned_by='',pin=None,rim=None,angle=None,radius_at=None,outward=False,about=PadRef(part=Part(inst='u1'),key=1,dx=0.0,dy=0.0,pin=None),run=None,freedom=<Freedom.FIXED: 'fixed'>,required=False,rotation_given=True)",
    "PlaceIntent(key='u6',item=fp:U6,kind='part',priority=<Priority.DEFAULT: 'default'>,rotation=0.0,face=<Face.FRONT: 'front'>,at=None,center=[Polar(radius=5.0,angle=90.0,about=Location(x=30,y=30)),Polar(radius=5.0,angle=90.0,about=Location(x=30,y=30))],edge=None,along=None,clearance=1.0,near=None,radius=3.0,step=0.2,rotations=[],why='',index=5,needs={},pin_x=None,pin_y=None,priority_source='auto',faces_note='',pinned_by='',pin=1,rim=None,angle=None,radius_at=None,outward=False,about=None,run=None,freedom=<Freedom.FIXED: 'fixed'>,required=False,rotation_given=True)",
]


def test_declarations_without_the_new_forms_digest_as_before():
    fps = [footprint("U%d" % n, 20, 20, w=4, h=2, inst="u%d" % n, nets=("A", "B")) for n in range(1, 8)]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    intents = [b.place(Part("u1"), at=Location(20, 20), rotation=90),
        b.place(Part("u2"), at=Pin(1, PadRef(Part("u1"), 2)), rotation=Turned(Part("u1"), 90)),
        b.place(Part("u3"), at=Beside(Part("u1"), Edge.SOUTH, align=(1, PadRef(Part("u1"), 1))), rotation=0),
        b.place(Part("u4"), at=Pin(2, X(PadRef(Part("u1"), 1)), 40.0), rotation=0),
        b.place(Part("u5"), at=Polar(5.0, 90.0, about=PadRef(Part("u1"), 1)), rotation=0),
        b.place(Part("u6"), at=Pin(1, Polar(5.0, 90.0, about=Location(30, 30))), rotation=0),]
    assert [reuse.canonical(i) for i in intents] == ACCEPTED_BEFORE
