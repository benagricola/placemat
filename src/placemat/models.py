"""A footprint's 3D model path, as the board a run writes should carry it.

A part library writes one `${KIPRJMOD}`-relative path per model, right for
a project at one depth; a module's project deeper in the tree gets the same
text and renders without bodies. A path that does not resolve from the
project's folder is re-anchored: its tail (the path less its leading `..`)
is looked for in the project's folder and each folder above it, up to the
workspace, and the first hit is written back relative to the project."""
from __future__ import annotations

import os
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


def reanchor(text: str, project_dir, stop=None) -> tuple:
    """(the path to write, or None to leave `text` as it is; whether the
    model was found at all). Only a `${KIPRJMOD}`-relative or a relative
    path is judged: another variable (a KiCad library's) or an absolute
    path is left, and counts as found."""
    norm = text.replace("\\", "/")
    if norm.startswith(PRJ):
        rel = norm[len(PRJ):].lstrip("/")
    elif norm.startswith("${") or norm.startswith("/") or (len(norm) > 1 and norm[1] == ":"):
        return None, True
    else:
        rel = norm
    project = Path(project_dir).resolve()
    if (project / rel).exists():
        return None, True
    tail = [p for p in rel.split("/") if p not in ("", ".", "..")]
    if not tail:
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
