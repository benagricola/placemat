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
