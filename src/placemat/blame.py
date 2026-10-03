"""What refused a scan's candidates, as data: the counts by kind, and for each kind the owners that caused most of them.

A scan (placer.ScanResult) counts its refusals (`rejected`), keeps the first refusal of each kind (`reasons`) and who was in
the way (`blockers`). `blame_of` turns that into a list of entries a finding carries as facts, and finding_text.blame_text
renders it as "courtyard x12: R1 front face x7, R2 front face x5"."""
from __future__ import annotations

from .occupancy import VIA_BUCKET

BLOCKED_BY = {"hole-to-hole": ("hole", "npth"),     # a bucket named for its rule: the obstacle kinds behind it
              "copper": ("pad", "through")}         # another part's pads and vias are copper refusals too
KNOWN_BUCKETS = frozenset(("courtyard", "edge", "reservation", "copper", "through", "npth", "hole-to-hole"))
DRAWN_KINDS = frozenset(("silk", "mask", "body"))
SHOWN = 3
"""How many kinds a blame names, most refusals first: a crowded board has forty and a reader needs one."""


def blame_of(result) -> list:
    """The rejection counts of a scan, and for each kind the owners that caused most of them (three, as `SHOWN`).
    Each entry is a dict: `form` "vias" (carried vias that could not give way), "rider" (a rider that refused candidates,
    named with its `reason`, however few it refused) or "kind" (the `label` of what refused, and its `owners`: each the
    Owner as JSON, the faces it holds and its count); and `count`."""
    shown = result.rejected.most_common(SHOWN)
    # a rider that refused candidates is named with its reason, however few it refused, and so is copper: whose
    # copper a via field met is what a far-face refusal needs to say
    shown += [kv for kv in result.rejected.most_common()
              if (kv[0].startswith("rider ") or kv[0] == "copper") and kv not in shown]
    shown += [kv for kv in result.rejected.most_common() if kv[0] == VIA_BUCKET and kv not in shown]
    out = []
    for kind, n in shown:
        if kind == VIA_BUCKET:
            out.append({"form": "vias", "count": n})
            continue
        if kind.startswith("rider "):
            out.append({"form": "rider", "count": n, "reason": result.reasons[kind].to_json()})
            continue
        if kind == "body":
            kind = "edge"       # "body box ... is past the rim's keep-in / outside the board / inside a cutout"
        # a drawn envelope's refusal (silk, a mask opening, a body) is counted under its sentence's first
        # word, the candidate's own name: it is shown as what it is, with the drawn things in the way
        drawn = kind not in KNOWN_BUCKETS
        owners = sorted(((owner, faces, count)
                         for (k, owner, faces), count in result.blockers.items()
                         if (k in DRAWN_KINDS if drawn else (k == kind or k in BLOCKED_BY.get(kind, ())))
                         and owner),
                        key=lambda t: -t[2])[:SHOWN]
        out.append({"form": "kind", "count": n, "label": "body, silk or mask" if drawn else kind,
                    "owners": [{"owner": o.to_json(), "faces": faces, "count": c} for o, faces, c in owners]})
    return out


def counts_of(rejected, top: int = SHOWN) -> list:
    """[[bucket, count], ...] of a scan's refusals, most first: what a slide or a block says of why nothing fitted."""
    return [[k, n] for k, n in rejected.most_common(top)]
