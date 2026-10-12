"""nets.layout.json, the capture's facts about each net, written by the Zener fork beside the netlist."""
import hashlib
import json

import pytest

from placemat.capture_nets import CaptureError, capture_beside, read_capture

NETLIST = "(export (version D))\n"


def write(folder, doc=None, netlist=NETLIST, **over):
    (folder / "default.net").write_text(netlist)
    base = {"version": 1, "generator": {"name": "benagricola/pcb", "version": "0.4.52", "git": "abc"},
            "netlist": {"file": "default.net", "sha256": hashlib.sha256(NETLIST.encode()).hexdigest()},
            "exports": ["types", "fields"],
            "nets": {"HV": {"type": "Power", "fields": {"clearance": {"value": 2.0, "unit": "mm"},
                                                        "voltage": {"value": 48.0, "unit": "V"}}},
                     "SIG": {"type": "Net", "fields": {}}}}
    base.update(over)
    (folder / "nets.layout.json").write_text(json.dumps(doc if doc is not None else base))
    return folder / "nets.layout.json"


def test_a_sidecar_gives_each_nets_type_fields_and_clearance(tmp_path):
    cap = read_capture(write(tmp_path))
    assert cap.nets["HV"].type == "Power" and cap.nets["HV"].clearance_mm == 2.0
    assert cap.nets["SIG"].clearance_mm is None
    assert cap.clearances() == {"HV": 2.0}
    assert cap.exports == frozenset({"types", "fields"}) and cap.generator["name"] == "benagricola/pcb"
    assert cap.nets_of_types(["Power"]) == ["HV"]


def test_a_sidecar_from_another_generation_is_refused(tmp_path):
    path = write(tmp_path)
    (tmp_path / "default.net").write_text("(export (version D) (other))\n")
    with pytest.raises(CaptureError) as e:
        read_capture(path)
    assert e.value.code == "stale" and e.value.facts["file"] == "default.net"


@pytest.mark.parametrize("doc, code", [({"version": 2}, "version"), ("not json", "unreadable")])
def test_an_unknown_or_unreadable_sidecar_is_refused(tmp_path, doc, code):
    write(tmp_path)
    (tmp_path / "nets.layout.json").write_text(doc if isinstance(doc, str) else json.dumps(doc))
    with pytest.raises(CaptureError) as e:
        read_capture(tmp_path / "nets.layout.json")
    assert e.value.code == code


def test_no_sidecar_beside_a_board_is_none(tmp_path):
    (tmp_path / "layout.kicad_pcb").write_text("")
    assert capture_beside(tmp_path / "layout.kicad_pcb") is None
    write(tmp_path)
    assert capture_beside(tmp_path / "layout.kicad_pcb").nets["HV"].type == "Power"


def test_stage_two_instances_and_pairs(tmp_path):
    cap = read_capture(write(tmp_path, exports=["types", "fields", "interfaces"],
                             interfaces={"USB": {"type": "Usb2", "members": {"D.P": "USB_D_P", "D.N": "USB_D_N"}},
                                         "USB.D": {"type": "DiffPair", "members": {"P": "USB_D_P", "N": "USB_D_N"}}},
                             pairs=[{"instance": "USB.D", "p": "USB_D_P", "n": "USB_D_N"}]))
    assert cap.instances["USB.D"].type == "DiffPair" and cap.pairs == (("USB.D", "USB_D_P", "USB_D_N"),)


def test_a_sidecar_missing_its_netlist_or_nets_is_refused(tmp_path):
    path = write(tmp_path, doc={"version": 1})
    with pytest.raises(CaptureError) as e:
        read_capture(path)
    assert e.value.code == "unreadable"
    path = write(tmp_path, nets=[1])
    with pytest.raises(CaptureError) as e:
        read_capture(path)
    assert e.value.code == "unreadable"
    path = write(tmp_path)
    (tmp_path / "default.net").unlink()
    with pytest.raises(CaptureError) as e:
        read_capture(path)
    assert e.value.code == "no_netlist"


def test_a_ohm_field_is_not_a_clearance(tmp_path):
    cap = read_capture(write(tmp_path, nets={"Z": {"type": "Net", "fields": {"impedance": {"value": 5, "unit": "Ohm"}}}}))
    assert cap.nets["Z"].clearance_mm is None and cap.clearances() == {}


@pytest.mark.parametrize("value", [0, -1, True, "2mm", float("nan"), float("inf")])
def test_invalid_clearance_is_a_structured_capture_error(tmp_path, value):
    side = write(tmp_path, nets={"V": {"type": "Power", "fields": {"clearance": {"value": value, "unit": "mm"}}}})
    with pytest.raises(CaptureError) as err:
        read_capture(side)
    assert err.value.code == "invalid_clearance" and err.value.facts["net"] == "V"


def test_unreadable_sidecar_and_netlist_paths_are_structured(tmp_path):
    with pytest.raises(CaptureError) as err:
        read_capture(tmp_path / "missing.json")
    assert err.value.code == "unreadable"
    for name in ("../default.net", "/tmp/default.net", 7):
        side = write(tmp_path)
        doc = json.loads(side.read_text())
        doc["netlist"] = {"file": name, "sha256": "wrong"}
        side.write_text(json.dumps(doc))
        with pytest.raises(CaptureError) as err:
            read_capture(side)
        assert err.value.code == "unreadable"


def test_malformed_field_records_are_structured(tmp_path):
    with pytest.raises(CaptureError) as err:
        read_capture(write(tmp_path, nets={"V": {"type": "Power", "fields": [1, 2]}}))
    assert err.value.code == "unreadable"


@pytest.mark.parametrize("members", [{"P": "A"}, {"P": "A", "N": "A"}, {"P": "A", "N": None}])
def test_malformed_diffpair_members_are_structured_capture_errors(tmp_path, members):
    side = write(tmp_path, interfaces={"D": {"type": "DiffPair", "members": members}}, exports=["interfaces"])
    with pytest.raises(CaptureError) as err:
        read_capture(side)
    assert err.value.code == "unreadable" and "DiffPair" in err.value.facts["missing"]
