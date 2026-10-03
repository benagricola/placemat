"""A footprint's 3D model path, as the board a run writes should carry it.

A part library writes one `${KIPRJMOD}`-relative path per model, right for
a project at one depth; a module's project deeper in the tree gets the same
text and renders without bodies. A path that does not resolve from the
project's folder is re-anchored: its tail (the path less its leading `..`)
is looked for in the project's folder and each folder above it, up to the
workspace, and the first hit is written back relative to the project."""
from __future__ import annotations

import os
import posixpath
from pathlib import Path

PRJ = "${KIPRJMOD}"


def workspace_root(start) -> Path | None:
    """The nearest folder at or above `start` whose pcb.toml declares
    `[workspace]`, as project.generator_inputs finds it."""
    d = Path(start).resolve()
    for folder in (d, *d.parents):
        toml = folder / "pcb.toml"
        if toml.is_file() and "[workspace]" in toml.read_text(errors="replace"):
            return folder
    return None


def models_line(done: dict) -> str:
    """The run's line for what the write did to model paths: "" when nothing."""
    n, missing = done.get("reanchored", 0), done.get("missing", [])
    if not n and not missing:
        return ""
    line = "%d re-anchored, %d not found" % (n, len(missing))
    return line + (" (%s%s)" % (", ".join(missing[:5]), ", ..." if len(missing) > 5 else "") if missing else "")


def reanchor(text: str, project_dir, stop=None) -> tuple:
    """(the path to write, or None to leave `text` as it is; whether the
    model was found at all). Only a path from the project's folder is
    judged - `${KIPRJMOD}/...`, `$(KIPRJMOD)/...` or `../...` - since every
    other form (an embedded model, another variable, a search-path alias, a
    library-relative or absolute path) KiCad finds elsewhere: those are
    left, and count as found. The tail searched for is the path, collapsed,
    less its leading `..`; a bare file name is not searched for."""
    norm = text.replace("\\", "/")
    for prefix in (PRJ, "$(KIPRJMOD)"):
        if norm.startswith(prefix):
            rel = norm[len(prefix):].lstrip("/")
            break
    else:
        if not norm.startswith("../"):
            return None, True
        rel = norm
    project = Path(project_dir).resolve()
    if (project / rel).exists():
        return None, True
    tail = posixpath.normpath(rel).split("/")
    while tail and tail[0] in ("..", "."):
        tail.pop(0)
    if len(tail) < 2:
        return None, False
    here = project
    stop = Path(stop).resolve() if stop is not None else None
    while True:
        hit = here.joinpath(*tail)
        if hit.is_file():
            return PRJ + "/" + Path(os.path.relpath(hit, project)).as_posix(), True
        if here == stop or here.parent == here:
            return None, False
        here = here.parent


# ---------------------------------------------------------------------------------------------------------------- resolution
# A model entry's text (as the footprint wrote it) to the file the 3D view reads, one resolver for everyone (the studio's 3D view,
# `placemat measure --models`). The order is the spec's (studio-3d-design.md, "Model sources and resolution"): the embedded file, an
# absolute path, ${KIPRJMOD} (after the write step's re-anchoring), another variable, a path from the project's folder, then a STEP
# beside a VRML model.
import hashlib
import re
from dataclasses import dataclass

EMBED = "kicad-embed://"
STEP_SUFFIXES = (".step", ".stp")
VRML_SUFFIXES = (".wrl", ".wrz")
_VAR = re.compile(r"\$[{(]([^})]+)[})]")
_STD_MODEL_DIRS = ("/usr/share/kicad/3dmodels", "/usr/local/share/kicad/3dmodels", "/Applications/KiCad/KiCad.app/Contents/SharedSupport/3dmodels",
                   "C:/Program Files/KiCad/share/kicad/3dmodels")


@dataclass(frozen=True)
class ModelRef:
    """What a model entry resolves to. `state`: ok (a file or an embedded file), none (the footprint declares no model), missing (not
    found: `text` keeps the path as written), hidden (the entry's hide flag), vrml (a VRML file with no STEP beside it). `why` is the
    reason for a state that has one, as a word: "not_found" or "vrml_only"; present.model_why says it in words."""
    state: str
    text: str = ""
    name: str = ""
    path: str = ""                  # the resolved file; "" for an embedded one
    embedded: str = ""              # the embedded file's name
    why: str = ""

    def to_json(self) -> dict:
        return {"state": self.state, "name": self.name, "text": self.text, "path": self.path, "embedded": self.embedded, "why": self.why}


def kicad_model_dirs(kicad_cli: str | None = None) -> list:
    """The folders KiCad's own 3D model library may be in: beside the real path of `kicad-cli`, then the standard install places."""
    dirs = []
    if kicad_cli:
        real = os.path.realpath(kicad_cli)
        dirs.append(os.path.normpath(os.path.join(os.path.dirname(real), "..", "share", "kicad", "3dmodels")))
    return [d for d in dirs + list(_STD_MODEL_DIRS) if os.path.isdir(d)]


def _step_beside(p: Path) -> Path | None:
    for s in (".step", ".stp", ".STEP", ".STP"):
        q = p.with_suffix(s)
        if q.is_file():
            return q
    return None


def _variable(name: str, env, extra_dirs, kicad_cli) -> list:
    """The folders a `${NAME}` may mean, in order: the process environment, then (for KiCad's own model variables) the library folders."""
    out = []
    if env.get(name):
        out.append(env[name])
    if re.fullmatch(r"KICAD\d*_3DMODEL_DIR|KISYS3DMOD", name):
        out += kicad_model_dirs(kicad_cli) + [d for d in extra_dirs if d]
    return out


def resolve_model(text: str, project_dir, *, stop=None, env=None, extra_dirs=(), kicad_cli: str | None = None, hidden: bool = False) -> ModelRef:
    """`text` (a footprint's model path as written) from the project at `project_dir` to a ModelRef. `stop` is the workspace folder
    `reanchor` searches up to; `env` the environment (default os.environ); `extra_dirs` more model folders (the setting
    `studio_3d_model_dirs`)."""
    text = text or ""
    if not text.strip():
        return ModelRef("none")
    name = text.replace("\\", "/").rsplit("/", 1)[-1]
    if text.startswith(EMBED):
        return ModelRef("hidden" if hidden else "ok", text, name, embedded=text[len(EMBED):])
    if hidden:
        return ModelRef("hidden", text, name)
    env = os.environ if env is None else env
    project = Path(project_dir)
    norm = text.replace("\\", "/")
    candidates: list = []
    m = _VAR.match(norm)
    if m:
        rest = norm[m.end():].lstrip("/")
        if m.group(1) == "KIPRJMOD":
            new, _ = reanchor(norm, project, stop)
            if new is not None:
                candidates.append(project / new[len(PRJ):].lstrip("/"))
            candidates.append(project / rest)
        else:
            candidates += [Path(d) / rest for d in _variable(m.group(1), env, extra_dirs, kicad_cli)]
    else:
        p = Path(norm)
        candidates.append(p if p.is_absolute() else project / p)
    for c in candidates:
        found = _file_or_step(c)
        if found is not None:
            kind = "vrml" if found.suffix.lower() in VRML_SUFFIXES else "ok"
            return ModelRef(kind, text, name, path=str(found), why="vrml_only" if kind == "vrml" else "")
    return ModelRef("missing", text, name, why="not_found")


def _file_or_step(p: Path) -> Path | None:
    """`p` as the file to read: a STEP beside a VRML path first (KiCad's own export substitutes it), else the file itself."""
    if p.suffix.lower() in VRML_SUFFIXES:
        step = _step_beside(p)
        if step is not None:
            return step
    return p if p.is_file() else None


_ids: dict = {}


def model_id(path: str, embedded: tuple | None = None) -> str:
    """A model's id: for a file the first 32 hex characters of the SHA-256 of its bytes (remembered by path, mtime and size), for an
    embedded one `e-` plus KiCad's own checksum of the embedded file, lower case."""
    if embedded is not None:
        return "e-" + str(embedded[1]).lower()[:32]
    st = os.stat(path)
    key = (path, st.st_mtime_ns, st.st_size)
    got = _ids.get(key)
    if got is None:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        got = _ids[key] = h.hexdigest()[:32]
        if len(_ids) > 4096:
            _ids.pop(next(iter(_ids)))
    return got


_FP_START = re.compile(r"^\t\(footprint ", re.M)
_REF = re.compile(r'\(property "Reference" "([^"]*)"')
_EMBEDDED = re.compile(r'\(name "([^"]+)"\)\s*\(type model\)(?:\s*\(data [^)]*\))?\s*\(checksum "([0-9A-Fa-f]+)"\)')
_sums: dict = {}


def embedded_checksums(pcb_path: str) -> dict:
    """{reference: {embedded model file name: KiCad's checksum}} read from a board file's text (pcbnew's Python does not expose the
    embedded files). Remembered by (path, mtime, size)."""
    st = os.stat(pcb_path)
    key = (pcb_path, st.st_mtime_ns, st.st_size)
    if key in _sums:
        return _sums[key]
    text = Path(pcb_path).read_text(encoding="utf-8", errors="replace")
    starts = [m.start() for m in _FP_START.finditer(text)] + [len(text)]
    out = {}
    for a, b in zip(starts, starts[1:]):
        block = text[a:b]
        files = dict(_EMBEDDED.findall(block))
        ref = _REF.search(block)
        if files and ref:
            out[ref.group(1)] = files
    _sums.clear()
    _sums[key] = out
    return out
