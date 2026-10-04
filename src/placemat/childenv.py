"""The environment placemat's child processes run in.

A child started with `env=None` inherits the C environment, which `os.environ`
does not show: pcbnew sets KIPRJMOD (to an empty string) there in a process
that creates or saves a board, and pcb takes the board's folder for it only
when it is unset. Every child that runs KiCad, pcb, or a placemat process that
does, is started with the dict `child_env` returns, so none of them sees it."""
from __future__ import annotations

import os

DISPLAY_VARS = ("DISPLAY", "WAYLAND_DISPLAY")


def child_env(*, headless: bool = True, extra: dict | None = None) -> dict[str, str]:
    """`os.environ` without KIPRJMOD, and (`headless`) without the display variables, so KiCad's tools
    do not open windows; `extra` is added last."""
    drop = ("KIPRJMOD",) + (DISPLAY_VARS if headless else ())
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env.update(extra or {})
    return env
