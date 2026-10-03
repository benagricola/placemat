"""Serve a scratch copy of a fixture project in a studio for the builder's browser checks (tests/browser/builder_check.py).

    python tests/browser/serve_builder.py <scratch dir> [module]

Stages the fixture module with its generation cached (no layout script), starts a studio on it with the board's generation
restored from that cache (`pcb layout` is not run) and prints the studio's address on the first line; runs until it is stopped."""
import shutil
import sys
import time
from pathlib import Path

from placemat import builder_worker, runner
from placemat.studio import Studio
from tests.builder_support import stage_project


def restore(src, run_dir, fresh, quiet, timeout=900, keep_renders=False):
    shutil.rmtree(src.layout_dir, ignore_errors=True)
    shutil.copytree(runner.cached_generation(src), src.layout_dir)
    return False


def reader(request, say):
    rec = builder_worker.read(request["zen"], request["name"], request.get("script"), request.get("fresh"), say)
    return {"ev": "board", **rec}


def main() -> int:
    dest = Path(sys.argv[1])
    module = sys.argv[2] if len(sys.argv) > 2 else "usbcells"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    stage_project(dest, module)
    runner.generate = restore
    studio = Studio(None, root=dest / "board", port=0, open_browser=False)
    studio.builder.reader = reader
    url = studio.start()
    print(url, flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        studio.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
