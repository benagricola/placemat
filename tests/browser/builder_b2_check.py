"""Browser check of the builder's rest of the vocabulary (rows, the order of decided placements, changing the outline, holes), after the new-board
flow of builder_check.py. Run as that is:

    python tests/browser/serve_builder.py <scratch dir> &
    uvx --with playwright python tests/browser/builder_b2_check.py <address> <out dir> [desktop|phone]
"""
import sys
import time

from playwright.sync_api import sync_playwright

import builder_check as bc

URL, OUT, MODE = bc.URL, bc.OUT, bc.MODE


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        page = browser.new_context(viewport=bc.SIZE, device_scale_factor=1).new_page()
        page.on("pageerror", lambda e: bc.errors.append("pageerror: %s" % e))
        page.on("console", lambda m: bc.errors.append("console: %s" % m.text) if m.type == "error" and not any(c in m.text for c in ("403", "409", "422", "423")) else None)
        page.goto(URL)
        bc.new_board(page)
        page.wait_for_selector("#ntabs button[data-nv=build]:not([hidden])" if MODE == "phone" else "#buildtab:not([hidden])", timeout=60000)
        page.wait_for_function("!document.querySelector('#bld') || document.querySelector('#bld').hidden", timeout=30000)
        page.click("#ntabs button[data-nv=build]" if MODE == "phone" else "#buildtab")
        page.wait_for_selector("#bt-list .bt-prow", timeout=120000)
        page.click("#bt-factsb")
        page.wait_for_selector("#fb-confirm", timeout=30000)
        bc.each(page, "input[data-ack]", lambda loc, i: loc.check())
        page.click("#fb-confirm")
        page.wait_for_selector(".bld-gate.open", timeout=30000)
        page.click("#bld-close")
        page.wait_for_selector("#bt-search:not([disabled])", timeout=30000)
        # two cells selected together go in a row
        page.click("#bt-list .bt-prow[data-key='usbpd.esd']")
        page.click("#bt-list .bt-prow[data-key='usbpd.sink'] input", modifiers=["Shift"]) if False else page.click("#bt-list .bt-prow[data-key='usbpd.sink']", modifiers=["Shift"])
        page.wait_for_selector("#bt-order")
        page.click("[data-edge=WEST]")
        page.wait_for_selector("[data-place]", timeout=30000)
        text = page.inner_text("#bt-menu")
        assert "a row along the west edge, centred" in text, text[:300]
        bc.shot(page, "20-row-menu")
        page.click(".bt-offer:has-text('centred') button[data-place]")
        page.wait_for_function("document.querySelector('#bt-list .bt-prow[data-key=\"usbpd.sink\"] .chip.decided')", timeout=120000)
        assert "in a row" in page.inner_text("#bt-list .bt-prow[data-key='usbpd.sink']")
        bc.shot(page, "21-row-placed")
        # a third item placed after it, then moved up among the decided placements
        page.click("#bt-list .bt-prow[data-key='usbpd.tcpc']")
        page.click("[data-edge=EAST]")
        page.wait_for_selector("[data-place]", timeout=30000)
        page.click(".bt-offer:has-text('in the middle of the east edge') button[data-place]")
        page.wait_for_function("document.querySelector('#bt-list .bt-prow[data-key=\"usbpd.tcpc\"] .chip.decided')", timeout=120000)
        page.wait_for_selector("#bt-up")                  # it is still the selection: its edit panel offers the move
        page.click("#bt-up")
        page.wait_for_function("document.querySelector('#bt-tl').innerText.includes('Move')", timeout=120000)
        bc.shot(page, "22-moved")
        # the outline: the rows stop a change of shape until they are taken apart
        page.click("#bt-outline")
        page.wait_for_selector("#ol-go")
        page.select_option("[data-ol=shape]", "disc")
        page.wait_for_function("document.querySelector('[data-ol=d]').value !== ''", timeout=10000)
        page.click("#ol-go")
        page.wait_for_selector("#ol-err:not(:empty), #ol-aff .bld-msg", timeout=30000)
        bc.shot(page, "23-shape-change")
        err = page.inner_text("#ol-err") + page.inner_text("#ol-aff")
        assert "stop being valid" in err or "row" in err, err
        # the same family: a corner is added, then a hole
        page.select_option("[data-ol=shape]", "rect_round")
        page.wait_for_function("document.querySelector('[data-ol=ra]')", timeout=10000)
        page.fill("[data-ol=ra]", "2")
        page.click("#ol-addhole")
        page.fill("[data-ho='0'][data-k=dia]", "3.2")
        page.fill("[data-ol=web]", "1")
        bc.shot(page, "24-outline-hole")
        page.click("#ol-go")
        page.wait_for_selector("#bld-oldlg", state="detached", timeout=120000)
        page.wait_for_function("document.querySelector('#bt-tl').innerText.includes('outline')", timeout=120000)
        bc.shot(page, "25-outline-changed")
        browser.close()
    if bc.errors:
        print("\n".join(bc.errors))
        return 1
    print("ok", MODE)
    return 0


if __name__ == "__main__":
    t = time.time()
    code = main()
    print("%.0f s" % (time.time() - t))
    sys.exit(code)
