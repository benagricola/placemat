"""Pin names for pads: read from the symbols the board's .zen files use,
through the generator's netlist, and addressed as PadRef(part, pin="VDD")."""
import dataclasses

import pytest

from placemat.layout import Board
from placemat.pins import netlist_symbols, symbol_pins, pin_names
from placemat.values import Location, PadRef, Part
from tests.fixtures import board_geometry, footprint

SYM = """(kicad_symbol_lib (version 20231120) (generator "x")
  (symbol "LDO_3V3" (pin_names (offset 0.254))
    (property "Reference" "U" (at 0 0 0))
    (symbol "LDO_3V3_0_1"
      (pin power_in line (at -5 2 0) (length 2.54) (name "VIN" (effects (font (size 1 1)))) (number "1" (effects (font (size 1 1)))))
      (pin power_out line (at 5 2 180) (length 2.54) (name "VOUT" (effects (font (size 1 1)))) (number "2" (effects (font (size 1 1)))))
    )
    (symbol "LDO_3V3_1_1"
      (pin power_in line (at 0 -5 90) (length 2.54) (name "GND" (effects (font (size 1 1)))) (number "3" (effects (font (size 1 1)))))
      (pin power_in line (at 1 -5 90) (length 2.54) (name "GND" (effects (font (size 1 1)))) (number "4" (effects (font (size 1 1)))))
    )
  )
)
"""

NET = """(export (version "E")
  (components
    (comp (ref "U1")
      (value "LDO")
      (libsource (lib "lib") (part "LDO_3V3") (description "unknown")))
    (comp (ref "C1")
      (value "100n")
      (libsource (lib "lib") (part "C") (description "unknown")))))
"""


def test_a_symbol_s_pins_are_read_by_number_across_its_units(tmp_path):
    (tmp_path / "ldo.kicad_sym").write_text(SYM)
    assert symbol_pins(tmp_path / "ldo.kicad_sym") == {"LDO_3V3": {"1": "VIN", "2": "VOUT", "3": "GND", "4": "GND"}}


def test_the_netlist_names_each_part_s_symbol(tmp_path):
    (tmp_path / "default.net").write_text(NET)
    assert netlist_symbols(tmp_path / "default.net") == {"U1": "LDO_3V3", "C1": "C"}


def test_pin_names_join_the_two_and_leave_a_symbol_it_cannot_find(tmp_path):
    (tmp_path / "ldo.kicad_sym").write_text(SYM)
    (tmp_path / "default.net").write_text(NET)
    names = pin_names(tmp_path / "default.net", [tmp_path / "ldo.kicad_sym"])
    assert names == {"U1": {"1": "VIN", "2": "VOUT", "3": "GND", "4": "GND"}}


def _board():
    fps = [footprint("U1", 20, 20, w=6, h=3, inst="ldo", nets=("VIN", "VOUT")),
           footprint("C1", 40, 40, inst="cin", nets=("VIN", "GND"))]
    g = board_geometry(fps, width=60, height=60)
    g = dataclasses.replace(g, pin_names={"U1": {"1": "VIN", "2": "VOUT"}})
    return Board(g, edge_margin=1.0)


def test_a_pad_is_addressed_by_its_pin_name():
    b = _board()
    b.place(Part("ldo"), at=Location(20, 20))
    b.place(Part("cin"), at=Location(40, 40))
    b.link(PadRef(Part("cin"), 1), PadRef(Part("ldo"), pin="VOUT"), limit_mm=40.0)
    plan = b.resolve()
    (l,) = plan.links
    assert l.b == ("U1", "2")


def test_an_unknown_pin_name_lists_the_part_s_names():
    b = _board()
    with pytest.raises(KeyError, match="VIN, VOUT"):
        b.link(PadRef(Part("cin"), 1), PadRef(Part("ldo"), pin="VDD"))


def test_a_name_on_several_pads_names_their_numbers():
    b = _board()
    b.geometry.pin_names["U1"]["3"] = "VIN"
    with pytest.raises(KeyError, match="1, 3"):
        b.link(PadRef(Part("cin"), 1), PadRef(Part("ldo"), pin="VIN"))


def test_a_component_named_apart_from_its_symbol_is_found_through_its_footprint(tmp_path):
    """The netlist's part is the component's name ("LDO-3V3-SOT23"), not the
    symbol's; the .zen that names the footprint also names the symbol."""
    (tmp_path / "parts").mkdir()
    (tmp_path / "parts" / "ldo.kicad_sym").write_text(SYM)
    (tmp_path / "Ldo.zen").write_text('Component(\n    name = "LDO-3V3-SOT23",\n'
                                      '    footprint = File("parts/SOT-23-3_LDO.kicad_mod"),\n'
                                      '    symbol = Symbol("parts/ldo.kicad_sym"),\n)\n')
    net = NET.replace('(value "LDO")', '(value "LDO")\n      (footprint "workspace_parts:SOT-23-3_LDO")') \
             .replace('(part "LDO_3V3")', '(part "LDO-3V3-SOT23")')
    (tmp_path / "default.net").write_text(net)
    names = pin_names(tmp_path / "default.net", [tmp_path / "parts" / "ldo.kicad_sym"], zens=[tmp_path / "Ldo.zen"])
    assert names["U1"]["2"] == "VOUT"


def test_measure_shows_each_pad_s_pin_name():
    from placemat import describe
    b = _board()
    fp = b.geometry.footprint("ldo")
    facts = [describe.pad_facts(fp, p, b.geometry) for p in fp.pads]
    assert [f["pin"] for f in facts] == ["VIN", "VOUT"]
    lines = describe.part_lines(fp, b.geometry, pads=True)
    assert any("pad 2" in l and "VOUT" in l for l in lines)
