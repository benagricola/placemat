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
import math
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
        if f is None:
            return None
        value = f.get("value") if isinstance(f, dict) else None
        if (not isinstance(f, dict) or f.get("unit") != "mm" or isinstance(value, bool)
                or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0):
            raise CaptureError("invalid_clearance", net=self.name, field="clearance", value=f)
        return float(value)


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
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CaptureError("unreadable", path=str(path), error=str(exc)) from None
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
    if not isinstance(name, str) or not name or Path(name).name != name:
        raise CaptureError("unreadable", path=str(path), field="netlist.file", value=name)
    netlist = path.parent / name
    if not netlist.is_file():
        raise CaptureError("no_netlist", path=str(path), file=name)
    try:
        actual_digest = hashlib.sha256(netlist.read_bytes()).hexdigest()
    except OSError as exc:
        raise CaptureError("unreadable", path=str(netlist), error=str(exc)) from None
    if actual_digest != digest:
        raise CaptureError("stale", path=str(path), file=name, generator=doc.get("generator"))
    try:
        return _capture(path, raw, doc)
    except CaptureError:
        raise
    except (KeyError, TypeError, AttributeError, ValueError):
        raise CaptureError("unreadable", path=str(path), missing="nets") from None


def _capture(path, raw, doc) -> Capture:
    nets = {name: NetRecord(name, r["type"], dict(r.get("fields") or {}),
                            tuple(Membership(m["instance"], m["type"], m["member"]) for m in r.get("interfaces") or ()))
            for name, r in doc["nets"].items()}
    for record in nets.values():
        record.clearance_mm
    instances = {p: Instance(p, r["type"], dict(r["members"])) for p, r in (doc.get("interfaces") or {}).items()}
    for instance in instances.values():
        if instance.type == "DiffPair" and (set(instance.members) != {"P", "N"} or
                any(not isinstance(n, str) or not n for n in instance.members.values()) or
                instance.members["P"] == instance.members["N"]):
            raise CaptureError("unreadable", path=str(path), missing="DiffPair %s P/N members" % instance.path)
    pairs = tuple((p["instance"], p["p"], p["n"]) for p in doc.get("pairs") or ())
    return Capture(str(path), hashlib.sha256(raw).hexdigest(), dict(doc.get("generator") or {}),
                   frozenset(doc.get("exports") or ()), nets, instances, pairs)


def capture_beside(pcb) -> Capture | None:
    path = Path(pcb).with_name(SIDECAR)
    return read_capture(path) if path.is_file() else None
