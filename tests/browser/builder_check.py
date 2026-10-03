"""Browser check of the studio's board builder (not part of the default suite): drives the page with Playwright on a scratch studio.

    python tests/browser/serve_builder.py <scratch dir> &          # prints the studio's address
    uvx --with playwright python tests/browser/builder_check.py <address> <out dir> [desktop|phone]

Chrome is /usr/bin/google-chrome. It walks the new-board flow (start view, the board, facts, outline, the script), then places parts
in the Build tab, and writes a screenshot at each step to <out dir>. It fails on a page error, a console error, or a step that does
not show what it should."""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

URL, OUT = sys.argv[1], Path(sys.argv[2])
MODE = sys.argv[3] if len(sys.argv) > 3 else "desktop"
RESUME = len(sys.argv) > 4 and sys.argv[4] == "resume"      # the script exists already: start at the Build tab
SIZE = {"desktop": {"width": 1280, "height": 900}, "phone": {"width": 412, "height": 892}}[MODE]
OUT.mkdir(parents=True, exist_ok=True)
errors = []


def shot(page, name):
    page.screenshot(path=str(OUT / ("%s-%s.png" % (MODE, name))), full_page=False)


def each(page, selector, f):
    """Apply `f(locator, index)` to each element matching, found again each time (the page redraws what it holds)."""
    for i in range(page.locator(selector).count()):
        f(page.locator(selector).nth(i), i)


def new_board(page):
    # the start view
    page.wait_for_selector("#bld-unbuilt button[data-build]", timeout=30000)
    shot(page, "01-start")
    assert "Boards with no layout" in page.inner_text("#bld-unbuilt")
    page.click("#bld-unbuilt button[data-build]")
    # the board is generated and read
    page.wait_for_selector("#bld-next", timeout=60000)
    shot(page, "02-board")
    assert "236" in page.inner_text("#bld-body")
    page.click("#bld-next")
    # facts: the stackup
    page.wait_for_selector("#st-write", timeout=30000)
    shot(page, "03-facts")
    each(page, "select[data-st][data-k=role]", lambda loc, i: loc.select_option("signal" if i in (0, 5) else "power"))
    each(page, "input[data-st][data-k=val]", lambda loc, i: loc.fill("1"))
    each(page, "input[data-st][data-k=mm]", lambda loc, i: loc.fill("0.2"))
    page.click("#st-write")
    page.wait_for_selector("#bld-msg .bld-msg", timeout=60000)
    shot(page, "04-stackup-written")
    # pairs: tick the first candidate
    page.wait_for_selector("#pr-write")
    page.check("input[data-pr='0'][data-k=on]") if page.query_selector("input[data-pr='0'][data-k=on]") else None
    for k, v in (("w", "0.2"), ("g", "0.15")):
        each(page, "input[data-pr][data-k=%s]" % k, lambda loc, i, v=v: loc.fill(v) if not loc.input_value() else None)
    page.click("#pr-write")
    page.wait_for_timeout(1500)
    # vias and minimums
    page.wait_for_selector("#vi-write")
    each(page, "select[data-vi]", lambda loc, i: loc.select_option("no") if i < 3 else None)
    page.fill("input[data-mn=track_mm]", "0.09")
    page.click("#vi-write")
    page.wait_for_timeout(1500)
    page.wait_for_selector("#rs-def")
    page.click("#rs-def")
    page.wait_for_timeout(1500)
    shot(page, "05-facts-all")
    # the outline
    page.click("button[data-step=outline]")
    page.wait_for_selector("#ol-go", timeout=30000)
    page.wait_for_function("document.querySelector('[data-ol=w]').value !== ''", timeout=10000)
    shot(page, "06-outline")
    w = page.input_value("[data-ol=w]")
    assert float(w) > 10, w
    page.select_option("[data-ol=shape]", "disc")
    page.wait_for_function("document.querySelector('[data-ol=d]').value !== ''", timeout=10000)
    d = float(page.input_value("[data-ol=d]"))
    assert d > 10
    page.select_option("[data-ol=shape]", "rect")
    page.wait_for_function("document.querySelector('[data-ol=w]').value !== ''", timeout=10000)
    page.fill("[data-ol=fill]", "40")
    page.wait_for_timeout(600)
    w2 = float(page.input_value("[data-ol=w]"))
    assert w2 > float(w), (w, w2)                     # a lower fill needs a bigger board
    page.fill("[data-ol=w]", "70")
    page.wait_for_timeout(600)
    assert "read only" in page.inner_text("#ol-fill") and "%" in page.inner_text("#ol-fill")
    shot(page, "07-outline-typed")
    page.click("#ol-go")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        page = browser.new_context(viewport=SIZE, device_scale_factor=1).new_page()
        page.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
        page.on("console", lambda m: errors.append("console: %s" % m.text) if m.type == "error" and "403" not in m.text else None)
        page.goto(URL)
        if not RESUME:
            new_board(page)
        # the studio watches the new script: the Build tab is there
        page.wait_for_selector("#ntabs button[data-nv=build]:not([hidden])" if MODE == "phone" else "#buildtab:not([hidden])", timeout=60000)
        page.wait_for_function("!document.querySelector('#bld') || document.querySelector('#bld').hidden", timeout=30000)
        if MODE == "phone":
            page.click("#ntabs button[data-nv=build]")
        else:
            page.click("#buildtab")
        page.wait_for_selector("#bt-list .bt-prow, #bt-open", timeout=60000)
        shot(page, "08-build-tab")
        page.wait_for_selector("#bt-list .bt-prow", timeout=120000)
        if "Placement waits for the facts" in page.inner_text("#tab-build"):
            # the gate: placement waits for the confirmation
            text = page.inner_text("#tab-build")
            assert "unplaced" in text and "Placement waits for the facts" in text, text[:300]
            page.click("#bt-factsb")
            page.wait_for_selector("#fb-confirm", timeout=30000)
            each(page, "input[data-ack]", lambda loc, i: loc.check())
            page.wait_for_timeout(800)
            shot(page, "09-confirm")
            page.click("#fb-confirm")
            try:
                page.wait_for_selector(".bld-gate.open", timeout=30000)
            except Exception:
                shot(page, "09b-confirm-failed")
                print(page.inner_text("#bld-msg"), page.inner_text("#bld-facts-bot"))
                raise
            page.click("#bld-close")
        page.wait_for_selector("#bt-search:not([disabled])", timeout=30000)
        # place a cell on the south edge, in the middle
        page.click("#bt-list .bt-prow[data-key='usbpd.esd']")
        page.wait_for_selector("#bt-chips")
        page.click("[data-edge=SOUTH]")
        page.wait_for_selector("[data-place]", timeout=30000)
        shot(page, "10-menu")
        assert "in the middle of the south edge" in page.inner_text("#bt-menu")
        page.click(".bt-offer:has-text('in the middle of the south edge') button[data-show]")
        page.wait_for_selector("#bt-diff .bld-pre", timeout=10000)
        shot(page, "11-show")
        page.click(".bt-offer:has-text('in the middle of the south edge') button[data-place]")
        page.wait_for_function("document.querySelector('#bt-list .bt-prow[data-key=\"usbpd.esd\"] .chip.decided')", timeout=120000)
        shot(page, "12-placed")
        # a second one beside it: Part target, a side
        page.click("#bt-list .bt-prow[data-key='usbpd.sink']")
        page.click("[data-chip=part]")
        page.click("#bt-list .bt-prow[data-key='usbpd.esd']")
        page.click("[data-side=NORTH]")
        page.wait_for_selector("[data-place]", timeout=30000)
        shot(page, "13-beside")
        page.click(".bt-offer:has-text('beside usbpd.esd, north') >> nth=0 >> button[data-place]")
        page.wait_for_function("document.querySelector('#bt-list .bt-prow[data-key=\"usbpd.sink\"] .chip.decided')", timeout=120000)
        # undo takes it back
        page.click("#bt-undo")
        page.wait_for_function("document.querySelector('#bt-list .bt-prow[data-key=\"usbpd.sink\"] .chip.unplaced')", timeout=120000)
        page.click("#bt-redo")
        page.wait_for_function("document.querySelector('#bt-list .bt-prow[data-key=\"usbpd.sink\"] .chip.decided')", timeout=120000)
        shot(page, "14-redo")
        # the timeline lists the builder's actions by their phrase
        assert "usbpd.esd" in page.inner_text("#bt-tl")
        browser.close()
    if errors:
        print("\n".join(errors))
        return 1
    print("ok", MODE)
    return 0


if __name__ == "__main__":
    t = time.time()
    code = main()
    print("%.0f s" % (time.time() - t))
    sys.exit(code)
