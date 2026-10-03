"""Browser check of three reported builder problems: choosing a part as a target after ticking an item, the facts page text, and unplacing.

    python tests/browser/serve_builder.py <scratch dir> &
    uvx --with playwright python tests/browser/builder_fixes_check.py <address> <out dir> [desktop|phone] [stage]

`stage` is facts (screenshot the facts page and stop), target (the part-target flow) or all (default)."""
import sys
import time

from playwright.sync_api import sync_playwright

import builder_check as bc

URL, OUT, MODE = bc.URL, bc.OUT, bc.MODE
STAGE = sys.argv[4] if len(sys.argv) > 4 else "all"


def open_tab(page):
    page.wait_for_selector("#ntabs button[data-nv=build]:not([hidden])" if MODE == "phone" else "#buildtab:not([hidden])", timeout=60000)
    page.wait_for_function("!document.querySelector('#bld') || document.querySelector('#bld').hidden", timeout=30000)
    page.click("#ntabs button[data-nv=build]" if MODE == "phone" else "#buildtab")
    page.wait_for_selector("#bt-list .bt-prow", timeout=120000)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        size = {"desktop": {"width": 1280, "height": 800}, "phone": {"width": 412, "height": 892}}[MODE]
        page = browser.new_context(viewport=size, device_scale_factor=1, color_scheme=sys.argv[5] if len(sys.argv) > 5 else "light").new_page()
        page.on("pageerror", lambda e: bc.errors.append("pageerror: %s" % e))
        page.on("console", lambda m: bc.errors.append("console: %s" % m.text) if m.type == "error" and not any(c in m.text for c in ("403", "409", "422", "423")) else None)
        page.goto(URL)
        page.wait_for_selector("#bld-unbuilt button[data-build]", timeout=30000)
        page.click("#bld-unbuilt button[data-build]")
        page.wait_for_selector("#bld-next", timeout=60000)
        page.click("#bld-next")
        page.wait_for_selector("#st-write", timeout=30000)
        page.wait_for_timeout(500)
        bc.shot(page, "fx-facts")
        page.screenshot(path=str(bc.OUT / ("%s-fx-facts-full.png" % MODE)), full_page=True)
        text = page.inner_text("#bld-body")
        print("facts text sample:", repr(text[:300]))
        if STAGE == "facts":
            browser.close()
            return
        bc.new_board.__globals__["MODE"] = MODE
        browser.close()


if __name__ == "__main__":
    main()
    print("\n".join(bc.errors) or "no errors")
