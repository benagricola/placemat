"""Regenerate the wide-route obstruction fixture from its fixed electrical geometry."""
import json
import pathlib
import uuid

HERE = pathlib.Path(__file__).resolve().parent
NETS = ("VB", "N1", "N2", "N3", "N4", "N5")


def item_id(name):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "placemat:obstructed-route:" + name))


def tht(ref, x, y, pads, fields=()):
    props = "".join('\t\t(property "%s" "%s" (at 0 0 0) (layer "F.Fab") (hide yes))\n' % kv for kv in fields)
    body = "".join('\t\t(pad "%s" thru_hole circle (at 0 %g) (size 1.7 1.7) (drill 1.0) '
                   '(layers "*.Cu" "*.Mask") (net %d "%s") (uuid "%s"))\n' %
                   (n, dy, NETS.index(net) + 1, net, item_id(ref + "." + n)) for n, dy, net in pads)
    return ('\t(footprint "fixture:THT" (layer "F.Cu") (uuid "%s") (at %g %g)\n'
            '\t\t(property "Reference" "%s" (at 0 -2 0) (layer "F.SilkS"))\n%s%s\t)\n' %
            (item_id(ref), x, y, ref, props, body))


def main():
    pcb = HERE / "layout.kicad_pcb"
    wall = [(str(i + 1), round(-5.08 + 2.54 * i, 2), "N%d" % (i + 1)) for i in range(5)]
    pcb.write_text('(kicad_pcb\n\t(version 20241229)\n\t(generator "fixture")\n'
                   '\t(general (thickness 1.6))\n\t(layers\n\t\t(0 "F.Cu" signal)\n'
                   '\t\t(2 "B.Cu" signal)\n\t\t(25 "Edge.Cuts" user)\n'
                   '\t\t(1 "F.Mask" user)\n\t\t(3 "B.Mask" user)\n'
                   '\t\t(5 "F.SilkS" user)\n\t\t(29 "F.Fab" user)\n\t)\n'
                   + "".join('\t(net %d "%s")\n' % (i + 1, n) for i, n in enumerate(NETS))
                   + tht("J1", 3, 6, [("1", 0, "VB")], [("Pm.I", "vb:3A")])
                   + tht("J2", 27, 6, [("1", 0, "VB")], [("Pm.I", "vb:3A")])
                   + tht("U1", 15, 6, wall)
                   + '\t(gr_rect (start 0 0) (end 30 12) (stroke (width 0.1) (type solid)) '
                     '(fill no) (layer "Edge.Cuts") (uuid "%s"))\n)\n' % item_id("outline"))
    pcb.with_suffix(".kicad_pro").write_text(json.dumps({
        "board": {"design_settings": {"rules": {"min_clearance": 0.2, "min_track_width": 0.2}}},
        "net_settings": {"classes": [{"name": "Default", "clearance": 0.2, "track_width": 0.2,
                                      "via_diameter": 0.6, "via_drill": 0.3}]}}, indent=2) + "\n")
    import pcbnew
    from placemat.kicad.write import load_board
    pcbnew.SaveBoard(str(pcb), load_board(pcb))


if __name__ == "__main__":
    main()
