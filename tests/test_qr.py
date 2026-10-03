"""The QR encoder behind the studio's phone address: its symbols agree with an independent encoder module for module, and
a decoder reads the exact address back out of them."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from placemat import qr

URLS = ["http://127.0.0.1:8765/?t=abc",
        "http://192.168.1.105:8765/?t=0CQ-nByVjQRlXBMR2LVbuQ#f=front&v=-3,-30,126,140&s=Core_layout.py",
        "http://192.168.1.105:8765/?t=0CQ-nByVjQRlXBMR2LVbuQ#s=boards%2Fcore%2FCore_layout.py&f=both&v=12.4,3.1,60,35.5&sel=usbpd.esd&tab=findings&fi=17",
        "http://studio.local:8765/?t=" + "x" * 150,
        "http://a/" + "9" * 260]
NODE_QR = Path(shutil.which("node") or "/nonexistent").resolve().parents[1] / "lib/node_modules/npm/node_modules/qrcode-terminal/vendor/QRCode" \
    if shutil.which("node") else None


def decode(matrix):
    """Read a symbol back: its format, the mask taken off, the codewords in order, the error correction checked, the text."""
    n = len(matrix)
    ver = (n - 17) // 4
    fmt = 0
    for i in range(15):                                                 # the first copy, read as it was written
        x, y = [(8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7), (8, 8), (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8)][i]
        fmt |= matrix[y][x] << i
    bits = fmt ^ 0x5412
    level, mask = {1: "L", 0: "M"}[bits >> 13], (bits >> 10) & 7
    g = qr._Grid(ver)
    grid = [row[:] for row in matrix]
    g.dark = grid
    g.mask(mask)                                                        # a mask applied twice is no mask
    words, i, s = [], 0, g.size
    cur, bitpos = 0, 0
    right = s - 1
    while right >= 1:
        if right == 6:
            right = 5
        for vert in range(s):
            for j in range(2):
                x = right - j
                y = s - 1 - vert if ((right + 1) & 2) == 0 else vert
                if not g.fn[y][x] and i < qr._raw_modules(ver) // 8 * 8:
                    cur = cur << 1 | grid[y][x]
                    bitpos += 1
                    if bitpos == 8:
                        words.append(cur)
                        cur, bitpos = 0, 0
                    i += 1
        right -= 2
    blocks, ecc_len, raw = qr._BLOCKS[level][ver], qr._ECC_PER_BLOCK[level][ver], qr._raw_modules(ver) // 8
    short, short_len = blocks - raw % blocks, raw // blocks
    lens = [short_len - ecc_len + (0 if b < short else 1) for b in range(blocks)]
    data = [[] for _ in range(blocks)]
    k = 0
    for col in range(max(lens)):
        for b in range(blocks):
            if col < lens[b]:
                data[b].append(words[k])
                k += 1
    ecc = [[] for _ in range(blocks)]
    for _ in range(ecc_len):
        for b in range(blocks):
            ecc[b].append(words[k])
            k += 1
    div = qr._rs_divisor(ecc_len)
    for b in range(blocks):
        assert qr._rs_remainder(data[b], div) == ecc[b], "error correction of block %d does not check" % b
    stream = "".join("{:08b}".format(w) for blk in data for w in blk)
    assert stream[:4] == "0100"
    cb = 8 if ver < 10 else 16
    count = int(stream[4:4 + cb], 2)
    body = stream[4 + cb:4 + cb + count * 8]
    return bytes(int(body[i:i + 8], 2) for i in range(0, len(body), 8)).decode("utf-8")


@pytest.mark.parametrize("url", URLS)
def test_a_decoder_reads_the_exact_address_back_at_each_error_correction_level(url):
    for level in ("M", "L"):
        assert decode(qr.encode(url, level)) == url


def test_every_mask_decodes_and_the_smallest_version_that_holds_the_text_is_used():
    url = URLS[1]
    sizes = {len(qr.encode(url, "M", mask=k)) for k in range(8)}
    assert len(sizes) == 1 and all(decode(qr.encode(url, "M", mask=k)) == url for k in range(8))
    assert len(qr.encode("a", "M")) == 21 and len(qr.encode("a" * 14, "M")) == 21 and len(qr.encode("a" * 15, "M")) == 25
    with pytest.raises(ValueError):
        qr.encode("a" * 1000)


def test_the_symbol_has_the_function_patterns_a_scanner_looks_for():
    m = qr.encode("hello")
    n = len(m)
    for cx, cy in ((0, 0), (n - 7, 0), (0, n - 7)):
        assert all(m[cy][cx + i] and m[cy + 6][cx + i] and m[cy + i][cx] and m[cy + i][cx + 6] for i in range(7))        # the finder's ring
        assert m[cy + 3][cx + 3] and not m[cy + 1][cx + 1]
    assert all(m[6][i] == (i % 2 == 0) for i in range(8, n - 8)) and m[n - 8][8]                                       # timing, dark module


@pytest.mark.skipif(NODE_QR is None or not (NODE_QR / "index.js").exists(), reason="no independent encoder on this machine")
def test_every_module_agrees_with_an_independent_encoder(tmp_path):
    cases = []
    for url in URLS:
        for level in ("M", "L"):
            ver = (len(qr.encode(url, level)) - 17) // 4
            for mask in (0, 3, 5, 7):
                cases.append({"text": url, "ver": ver, "level": {"L": 1, "M": 0}[level], "mask": mask, "mine": qr.encode(url, level, mask=mask)})
    js = tmp_path / "x.js"
    js.write_text("""const QRCode = require(%s);
const cases = JSON.parse(require('fs').readFileSync(process.argv[2], 'utf8'));
const out = cases.map(c => { const q = new QRCode(c.ver, c.level); q.addData(c.text); q.makeImpl(false, c.mask); return q.modules.map(r => r.map(v => !!v)); });
console.log(JSON.stringify(out));""" % json.dumps(str(NODE_QR)))
    data = tmp_path / "cases.json"
    data.write_text(json.dumps(cases))
    done = subprocess.run(["node", str(js), str(data)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    theirs = json.loads(done.stdout)
    for c, other in zip(cases, theirs):
        assert other == c["mine"], (c["text"][:40], c["ver"], c["level"], c["mask"])


def test_the_svg_and_the_terminal_text_draw_the_same_symbol():
    m = qr.encode("http://192.168.0.2:8765/?t=abc")
    svg = qr.to_svg(m)
    assert svg.startswith("<svg") and "viewBox=\"0 0 %d %d\"" % (len(m) + 8, len(m) + 8) in svg and svg.count("h1v1h-1z") == sum(map(sum, m))
    text = qr.to_terminal(m)
    lines = text.splitlines()
    assert len(lines) == (len(m) + 4 + 1) // 2 and all(len(line) == len(m) + 4 for line in lines)
    assert set(text) <= set("█▀▄ \n")
