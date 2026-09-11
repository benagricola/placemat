#!/usr/bin/env python3
"""Fetch the missing datasheet PDF for every part wrapper, from its pinned LCSC code.

The workspace rule is that an active part cannot be used without its datasheet
sitting in its own folder. This fills the gaps: for each part folder with no
PDF, read the LCSC code from the wrapper `.zen`, pull the product page, take
the datasheet link off it, download and verify.

Verification is not optional - a wrong PDF is worse than a missing one. A
download is kept only if it starts with the PDF magic, is big enough to be a
real document, and its text names the part. Anything that fails the last
check is kept but reported UNVERIFIED, so a human looks - distinguishing a
drawing with no extractable text from one whose text names something else.

  placemat datasheets                 # every part missing one
  placemat datasheets --list          # what is missing, fetch nothing
  placemat datasheets TRINAMIC_TMC2160A_TA ...   # named parts only
"""
import argparse
import glob
import os
import re
import subprocess
import sys
import time

sys.dont_write_bytecode = True   # no __pycache__ beside the sources

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
PRODUCT = "https://www.lcsc.com/product-detail/%s.html"
MIN_BYTES = 20000                # anything smaller is an error page, not a datasheet
PAUSE = 2.0                      # between product-page hits; the host throttles


def part_folders():
    """[(folder, wrapper .zen)] for every part the PROJECT holds.

    Where the parts are is the project's to say, so this does not go looking:
    a project whose footprints live somewhere else says so in its pcb.toml and
    everything that reads parts agrees about where they were."""
    from placemat.project import active
    out = []
    for name, d in sorted(active().part_dirs.items()):
        zen = os.path.join(os.path.dirname(d), name + ".zen")
        if not os.path.exists(zen):
            inner = os.path.join(d, name + ".zen")
            zen = inner if os.path.exists(inner) else None
        out.append((d, zen))
    return out


def part_meta(zen):
    """(lcsc, mpn, manufacturer) as the wrapper pins them."""
    if not zen or not os.path.exists(zen):
        return None, None, None
    src = open(zen).read()
    lcsc = re.search(r'"LCSC"\s*:\s*"(C\d+)"', src)
    mpn = re.search(r'\bmpn\s*=\s*"([^"]+)"', src)
    man = re.search(r'\bmanufacturer\s*=\s*"([^"]+)"', src)
    prop_mpn = re.search(r'"MPN"\s*:\s*"([^"]+)"', src)
    return (lcsc.group(1) if lcsc else None,
            (mpn or prop_mpn).group(1) if (mpn or prop_mpn) else None,
            man.group(1) if man else None)


def has_datasheet(folder):
    return bool(glob.glob(os.path.join(folder, "*.pdf")) +
                glob.glob(os.path.join(folder, "*.PDF")))


def curl(url, out=None, timeout=90):
    cmd = ["curl", "-sS", "-L", "--max-time", str(timeout), "-A", UA]
    cmd += ["-o", out] if out else []
    cmd += [url]
    r = subprocess.run(cmd, capture_output=not out, text=not out)
    return (r.returncode == 0, "" if out else (r.stdout or ""))


def datasheet_url(lcsc):
    """The datasheet link off the LCSC product page, certifications excluded."""
    ok, html = curl(PRODUCT % lcsc, timeout=60)
    if not ok or not html:
        return None
    hits = [u for u in re.findall(r'https://datasheet\.lcsc\.com/[^"\' \\]+?\.pdf', html)
            if "/certification/" not in u and "/rohs/" not in u]
    seen = []
    for u in hits:
        if u not in seen:
            seen.append(u)
    return seen[0] if seen else None


def pdf_text(path):
    """The whole document. A family datasheet names the part deep inside (the
    connector series sheet lists every variant), so first-page matching alone
    reports false mismatches."""
    try:
        r = subprocess.run(["pdftotext", path, "-"],
                           capture_output=True, text=True, timeout=180)
        return r.stdout or ""
    except Exception:
        return ""


def mentions(text, mpn):
    """Does the document name the part? Compared on alphanumerics only, and on
    the stem too, because a datasheet covers a family (TMC2160 for TMC2160A-TA)
    and packaging suffixes never appear in the title."""
    if not text or not mpn:
        return False
    flat = re.sub(r"[^A-Za-z0-9]", "", text).upper()
    cand = re.sub(r"[^A-Za-z0-9]", "", mpn).upper()
    while len(cand) >= 5:
        if cand in flat:
            return True
        cand = cand[:-1]
    return False


def filename(folder, man, mpn, lcsc):
    def slug(s):
        return re.sub(r"[^A-Za-z0-9]+", "-", s or "").strip("-")
    stem = "-".join(x for x in (slug(man), slug(mpn)) if x) or os.path.basename(folder)
    return os.path.join(folder, "%s_%s.pdf" % (stem, lcsc))



def parser():
    """The arguments this command takes."""
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("parts", nargs="*", help="part folder names (default: all missing one)")
    ap.add_argument("--list", action="store_true", help="report what is missing, fetch nothing")
    ap.add_argument("--force", action="store_true", help="fetch even when a PDF is present")
    return ap


def main(args=None):
    a = args if args is not None else parser().parse_args()

    todo, no_code = [], []
    for folder, zen in part_folders():
        name = os.path.basename(folder)
        if a.parts and name not in a.parts:
            continue
        if has_datasheet(folder) and not a.force:
            continue
        lcsc, mpn, man = part_meta(zen)
        (todo if lcsc else no_code).append((folder, name, lcsc, mpn, man))

    print("%d part folder(s) without a datasheet; %d have no LCSC code in a wrapper"
          % (len(todo) + len(no_code), len(no_code)))
    for _f, name, _l, _m, _man in no_code:
        print("  NO CODE   %s" % name)
    if a.list:
        for _f, name, lcsc, mpn, _man in todo:
            print("  MISSING   %-42s %-10s %s" % (name, lcsc, mpn or ""))
        return

    ok = unverified = failed = 0
    for i, (folder, name, lcsc, mpn, man) in enumerate(todo, 1):
        print("[%d/%d] %-42s %s" % (i, len(todo), name, lcsc), flush=True)
        url = datasheet_url(lcsc)
        if not url:
            print("        FAILED   no datasheet link on the product page")
            failed += 1
            time.sleep(PAUSE)
            continue
        dst = filename(folder, man, mpn, lcsc)
        got, _ = curl(url, out=dst, timeout=180)
        size = os.path.getsize(dst) if os.path.exists(dst) else 0
        head = open(dst, "rb").read(8) if size else b""
        # some hosts serve the file with a UTF-8 BOM in front of the magic
        if not got or b"%PDF-" not in head or size < MIN_BYTES:
            print("        FAILED   %s (%d bytes)" % (url, size))
            if os.path.exists(dst):
                os.remove(dst)
            failed += 1
        else:
            text = pdf_text(dst)
            if mentions(text, mpn):
                print("        ok       %s (%d KB)" % (os.path.basename(dst), size // 1024))
                ok += 1
            elif len(text.split()) < 20:
                print("        UNVERIFIED %s (%d KB) - a drawing with no extractable "
                      "text; look at it" % (os.path.basename(dst), size // 1024))
                unverified += 1
            else:
                print("        UNVERIFIED %s (%d KB) - text does not name %s anywhere; "
                      "look at it" % (os.path.basename(dst), size // 1024, mpn))
                unverified += 1
        time.sleep(PAUSE)

    print("\n%d fetched and verified, %d unverified, %d failed" % (ok, unverified, failed))


if __name__ == "__main__":
    main()
