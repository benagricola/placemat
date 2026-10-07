"""nets.layout.json: what the capture says about each net, written beside the netlist by the Zener fork's `pcb layout`
(benagricola/pcb, crates/pcb-layout/src/nets_layout.rs): its type and fields, and from the fork's stage 2 the interface
instances it belongs to and the differential pairs. Read here as records; a phase selects by them
(kicad/phase_select.py) and the route takes each net's `clearance` field (kicad/net_clearance.py).

The file names the netlist it was written with and that file's sha256. A sidecar whose digest does not match the
netlist beside it was left by another generation (a stale file from an earlier toolchain) and is refused."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

SIDECAR = "nets.layout.json"
VERSION = 1


class CaptureError(ValueError):
    """A sidecar placemat cannot use: `code` (unreadable, version, no_netlist, stale) and `facts`."""

    def __init__(self, code: str, **facts):
        self.code, self.facts = code, dict(facts)
        super().__init__("%s: %s %s" % (SIDECAR, code, json.dumps(self.facts, sort_keys=True)))


@dataclass(frozen=True)
class Membership:
    instance: str
    type: str
    member: str


@dataclass(frozen=True)
class NetRecord:
    name: str
    type: str
    fields: dict
    interfaces: tuple = ()

    @property
    def clearance_mm(self) -> float | None:
        f = self.fields.get("clearance")
        return float(f["value"]) if isinstance(f, dict) and f.get("unit") == "mm" else None


@dataclass(frozen=True)
class Instance:
    path: str
    type: str
    members: dict


@dataclass(frozen=True)
class Capture:
    path: str
    digest: str
    generator: dict
    exports: frozenset
    nets: dict
    instances: dict
    pairs: tuple

    def clearances(self) -> dict:
        return {n: r.clearance_mm for n, r in sorted(self.nets.items()) if r.clearance_mm is not None}

    def nets_of_types(self, types) -> list:
        wanted = set(types)
        return sorted(n for n, r in self.nets.items() if r.type in wanted)


def read_capture(path) -> Capture:
    path = Path(path)
    raw = path.read_bytes()
    try:
        doc = json.loads(raw)
    except ValueError:
        raise CaptureError("unreadable", path=str(path)) from None
    if not isinstance(doc, dict) or doc.get("version") != VERSION:
        raise CaptureError("version", path=str(path), version=doc.get("version") if isinstance(doc, dict) else None,
                           reads=VERSION)
    try:
        name, digest = doc["netlist"]["file"], doc["netlist"]["sha256"]
    except (KeyError, TypeError):
        raise CaptureError("unreadable", path=str(path), missing="netlist") from None
    netlist = path.parent / name
    if not netlist.is_file():
        raise CaptureError("no_netlist", path=str(path), file=name)
    if hashlib.sha256(netlist.read_bytes()).hexdigest() != digest:
        raise CaptureError("stale", path=str(path), file=name, generator=doc.get("generator"))
    try:
        return _capture(path, raw, doc)
    except (KeyError, TypeError, AttributeError):
        raise CaptureError("unreadable", path=str(path), missing="nets") from None


def _capture(path, raw, doc) -> Capture:
    nets = {name: NetRecord(name, r["type"], dict(r.get("fields") or {}),
                            tuple(Membership(m["instance"], m["type"], m["member"]) for m in r.get("interfaces") or ()))
            for name, r in doc["nets"].items()}
    instances = {p: Instance(p, r["type"], dict(r["members"])) for p, r in (doc.get("interfaces") or {}).items()}
    pairs = tuple((p["instance"], p["p"], p["n"]) for p in doc.get("pairs") or ())
    return Capture(str(path), hashlib.sha256(raw).hexdigest(), dict(doc.get("generator") or {}),
                   frozenset(doc.get("exports") or ()), nets, instances, pairs)


def capture_beside(pcb) -> Capture | None:
    path = Path(pcb).with_name(SIDECAR)
    return read_capture(path) if path.is_file() else None
