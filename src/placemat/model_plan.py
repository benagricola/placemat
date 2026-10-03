"""What the plan document says about 3D models: for each member of a placed item, its model entries resolved (models.resolve_model), each
with its id and its placement matrix (model_place.placement) from the model frame to the scene frame; for the plan, the table of distinct
models and the stackup. The page applies the matrices and never recomputes the chain; resolution happens here, in the resolve's own
process, from the footprints as the generator left them and the plan's transform to where each stands now.

A `ModelContext` is made once per resolve from the board file the plan was read from. It remembers the models it has seen, so the
studio can queue each distinct one for the converter (`jobs`)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from . import model_place
from .models import EMBED, embedded_checksums, model_id, resolve_model, workspace_root
from .placement import Placement


class ModelContext:
    def __init__(self, pcb_path, model_dirs=(), kicad_cli: str | None = None):
        self.pcb = str(pcb_path)
        self.project_dir = Path(self.pcb).parent
        self.stop = workspace_root(self.project_dir)
        self.model_dirs = tuple(d for d in model_dirs if d)
        self.kicad_cli = kicad_cli
        self.thickness = model_place.board_thickness(self.pcb)
        self.seen: dict = {}                  # id -> table entry
        self.jobs_by_id: dict = {}            # id -> converter job
        self._sums = None

    def _checksums(self) -> dict:
        if self._sums is None:
            try:
                self._sums = embedded_checksums(self.pcb)
            except OSError:
                self._sums = {}
        return self._sums

    def entry(self, fp, e) -> dict:
        """One model entry of footprint `fp` as the plan carries it (without the matrix)."""
        text, shown, opacity = e[0], (e[4] if len(e) > 4 else True), (e[5] if len(e) > 5 else 1.0)
        ref = resolve_model(text, self.project_dir, stop=self.stop, extra_dirs=self.model_dirs, kicad_cli=self.kicad_cli, hidden=not shown)
        out = {"id": "", "state": ref.state, "name": ref.name, "opacity": opacity, "why": ref.why}
        if ref.state in ("ok", "vrml"):
            if ref.embedded:
                sums = self._checksums().get(fp.ref, {})
                if ref.embedded not in sums:
                    out.update(state="missing", why="the embedded model %s has no checksum on the board file" % ref.embedded)
                    return out
                mid, kind, job = model_id("", (ref.embedded, sums[ref.embedded])), "embedded", {"kind": "embedded", "board": self.pcb, "ref": fp.ref, "name": ref.embedded}
            else:
                try:
                    mid = model_id(ref.path)
                except OSError as e:
                    out.update(state="missing", why="model cannot be read: %s" % e)
                    return out
                kind = "vrml" if ref.state == "vrml" else "file"
                job = {"kind": kind, "path": ref.path, "name": Path(ref.path).name}
            out["id"] = mid
            if mid not in self.seen:
                self.seen[mid] = {"name": ref.name, "source": kind, "state": "ok"}
                self.jobs_by_id[mid] = dict(job, id=mid)
        return out

    def members(self, plan, fp) -> list:
        """`fp`'s models for the plan document: each entry resolved, with its matrix to where the plan has put the part."""
        if not getattr(fp, "models", ()):
            return [{"id": "", "state": "none", "name": "", "opacity": 1.0, "why": "the footprint declares no 3D model", "matrix": None}]
        occ = plan.occupancy
        geom = occ.items[fp.ref]
        t = occ._transform(SimpleNamespace(reference=Placement(fp.location, fp.rotation, fp.face)), geom.reference)
        flipped = geom.reference.face != fp.face
        out = []
        for e in fp.models:
            d = self.entry(fp, e)
            d["matrix"] = model_place.placement(e, location=(fp.location.x, fp.location.y), rotation=fp.rotation, face=fp.face.value, to=t,
                                                flipped=flipped, thickness=self.thickness) if d["id"] else None
            out.append(d)
        return out

    def table(self) -> dict:
        return {k: dict(v) for k, v in sorted(self.seen.items())}

    def new_jobs(self, known: set) -> list:
        """The converter jobs for models seen that `known` (ids already sent) does not have; `known` is updated."""
        out = [self.jobs_by_id[i] for i in self.seen if i not in known]
        known.update(j["id"] for j in out)
        return out

    def stackup(self, geometry) -> dict:
        return {"thickness": round(self.thickness, 4), "copper": {l.value: round(v, 4) for l, v in sorted(geometry.copper_mm.items(), key=lambda kv: kv[0].value)}}
