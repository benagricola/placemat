"""A QR code encoder for the studio's "open this on your phone" address: byte mode, error correction L or M, versions
1 to 20, no dependency. Written for placemat from the QR Code specification (ISO/IEC 18004) with the layout of the
public-domain-style reference implementations in mind (Nayuki's QR Code generator, MIT); checked against an
independent encoder and a decoder in tests/test_qr.py. The page works offline, so nothing is fetched to draw it.

    encode("http://192.168.1.5:8765/?t=abc")  -> a square list of rows of bools, True a dark module
    to_svg(matrix)                             -> an SVG document
    to_terminal(matrix)                        -> text in Unicode half blocks, for a terminal"""
from __future__ import annotations

# Error correction codewords per block and number of blocks, by version 1..20 (index 0 unused), for levels L and M.
_ECC_PER_BLOCK = {"L": (0, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30, 22, 24, 28, 30, 28, 28),
                  "M": (0, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26)}
_BLOCKS = {"L": (0, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 7, 8),
           "M": (0, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16)}
_FORMAT_BITS = {"L": 1, "M": 0}
MAX_VERSION = 20


def _raw_modules(ver: int) -> int:
    """The modules of version `ver` that are not function patterns."""
    n = (16 * ver + 128) * ver + 64
    if ver >= 2:
        a = ver // 7 + 2
        n -= (25 * a - 10) * a - 55
        if ver >= 7:
            n -= 36
    return n


def _data_codewords(ver: int, ecl: str) -> int:
    return _raw_modules(ver) // 8 - _ECC_PER_BLOCK[ecl][ver] * _BLOCKS[ecl][ver]


def _gf_mul(x: int, y: int) -> int:
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree: int) -> list:
    out, root = [0] * (degree - 1) + [1], 1
    for _ in range(degree):
        for j in range(degree):
            out[j] = _gf_mul(out[j], root)
            if j + 1 < degree:
                out[j] ^= out[j + 1]
        root = _gf_mul(root, 2)
    return out


def _rs_remainder(data: list, divisor: list) -> list:
    out = [0] * len(divisor)
    for b in data:
        factor = b ^ out.pop(0)
        out.append(0)
        for i, coef in enumerate(divisor):
            out[i] ^= _gf_mul(coef, factor)
    return out


def _codewords(text: bytes, ver: int, ecl: str) -> list:
    """The data, its error correction and the interleaving of both, as codewords."""
    bits = [0, 1, 0, 0]
    count_bits = 8 if ver < 10 else 16
    bits += [(len(text) >> i) & 1 for i in reversed(range(count_bits))]
    for byte in text:
        bits += [(byte >> i) & 1 for i in reversed(range(8))]
    capacity = _data_codewords(ver, ecl) * 8
    bits += [0] * min(4, capacity - len(bits))
    bits += [0] * (-len(bits) % 8)
    data = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0xEC
    while len(data) < capacity // 8:
        data.append(pad)
        pad ^= 0xEC ^ 0x11
    blocks, ecc_len, raw = _BLOCKS[ecl][ver], _ECC_PER_BLOCK[ecl][ver], _raw_modules(ver) // 8
    short = blocks - raw % blocks
    short_len = raw // blocks
    divisor, parts, k = _rs_divisor(ecc_len), [], 0
    for i in range(blocks):
        n = short_len - ecc_len + (0 if i < short else 1)
        chunk = data[k:k + n]
        k += n
        parts.append((chunk, _rs_remainder(chunk, divisor)))
    out = []
    for i in range(short_len - ecc_len + 1):                        # the data, a column at a time (a short block has no last one)
        for j, (chunk, _) in enumerate(parts):
            if i < len(chunk):
                out.append(chunk[i])
    for i in range(ecc_len):
        out += [ecc[i] for _, ecc in parts]
    return out


def _alignment_positions(ver: int) -> list:
    if ver == 1:
        return []
    n, size = ver // 7 + 2, ver * 4 + 17
    step = (ver * 4 + n * 2 + 1) // (n * 2 - 2) * 2
    return list(reversed([size - 7 - i * step for i in range(n - 1)] + [6]))


class _Grid:
    def __init__(self, ver: int):
        self.ver, self.size = ver, ver * 4 + 17
        self.dark = [[False] * self.size for _ in range(self.size)]
        self.fn = [[False] * self.size for _ in range(self.size)]
        self._patterns()

    def put(self, x: int, y: int, dark: bool) -> None:
        self.dark[y][x] = dark
        self.fn[y][x] = True

    def _patterns(self) -> None:
        s = self.size
        for i in range(s):                                          # timing
            self.put(6, i, i % 2 == 0)
            self.put(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (s - 4, 3), (3, s - 4)):             # finders with their separators
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < s and 0 <= y < s:
                        self.put(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        pos = _alignment_positions(self.ver)
        for i, cy in enumerate(pos):
            for j, cx in enumerate(pos):
                if (i == 0 and j == 0) or (i == 0 and j == len(pos) - 1) or (i == len(pos) - 1 and j == 0):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.put(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)
        self.format(0, "M")                                         # reserves the format areas
        if self.ver >= 7:
            rem = self.ver
            for _ in range(12):
                rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
            bits = self.ver << 12 | rem
            for i in range(18):
                a, b = s - 11 + i % 3, i // 3
                self.put(a, b, bool((bits >> i) & 1))
                self.put(b, a, bool((bits >> i) & 1))

    def format(self, mask: int, ecl: str) -> None:
        data = _FORMAT_BITS[ecl] << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        s = self.size
        for i in range(6):
            self.put(8, i, bool((bits >> i) & 1))
        self.put(8, 7, bool((bits >> 6) & 1))
        self.put(8, 8, bool((bits >> 7) & 1))
        self.put(7, 8, bool((bits >> 8) & 1))
        for i in range(9, 15):
            self.put(14 - i, 8, bool((bits >> i) & 1))
        for i in range(8):
            self.put(s - 1 - i, 8, bool((bits >> i) & 1))
        for i in range(8, 15):
            self.put(8, s - 15 + i, bool((bits >> i) & 1))
        self.put(8, s - 8, True)

    def place(self, codewords: list) -> None:
        s, i = self.size, 0
        right = s - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(s):
                for j in range(2):
                    x = right - j
                    y = s - 1 - vert if ((right + 1) & 2) == 0 else vert
                    if not self.fn[y][x] and i < len(codewords) * 8:
                        self.dark[y][x] = bool((codewords[i >> 3] >> (7 - (i & 7))) & 1)
                        i += 1
            right -= 2

    def mask(self, k: int) -> None:
        for y in range(self.size):
            for x in range(self.size):
                inv = (((x + y) % 2 == 0, y % 2 == 0, x % 3 == 0, (x + y) % 3 == 0, (x // 3 + y // 2) % 2 == 0,
                        x * y % 2 + x * y % 3 == 0, (x * y % 2 + x * y % 3) % 2 == 0, ((x + y) % 2 + x * y % 3) % 2 == 0))[k]
                if inv and not self.fn[y][x]:
                    self.dark[y][x] = not self.dark[y][x]

    def penalty(self) -> int:
        s, d, score = self.size, self.dark, 0
        lines = [row for row in d] + [[d[y][x] for y in range(s)] for x in range(s)]
        for line in lines:
            run = 1
            for a, b in zip(line, line[1:]):
                if a == b:
                    run += 1
                else:
                    score += 3 + run - 5 if run >= 5 else 0
                    run = 1
            score += 3 + run - 5 if run >= 5 else 0
            text = "".join("1" if v else "0" for v in line)
            for pat in ("10111010000", "00001011101"):
                start = text.find(pat)
                while start >= 0:
                    score += 40
                    start = text.find(pat, start + 1)
        for y in range(s - 1):
            for x in range(s - 1):
                if d[y][x] == d[y][x + 1] == d[y + 1][x] == d[y + 1][x + 1]:
                    score += 3
        total, dark = s * s, sum(map(sum, d))
        k = -(-abs(dark * 20 - total * 10) // total) - 1            # whole steps of 5 percent the dark share is from half
        score += 10 * max(0, k)
        return score


def encode(text: str, ecl: str = "M", mask: int | None = None) -> list:
    """The QR symbol for `text` (UTF-8, byte mode) as rows of bools. `ecl` is "L" or "M"; the smallest version that holds
    it is used, and, unless `mask` is given, the mask pattern with the lowest penalty."""
    data = text.encode("utf-8")
    for level in ((ecl,) if ecl == "L" else ("M", "L")):
        for ver in range(1, MAX_VERSION + 1):
            if len(data) * 8 + 4 + (8 if ver < 10 else 16) <= _data_codewords(ver, level) * 8:
                break
        else:
            continue
        break
    else:
        raise ValueError("%d bytes do not fit a QR code of version %d" % (len(data), MAX_VERSION))
    words = _codewords(data, ver, level)
    best = None
    for k in ([mask] if mask is not None else range(8)):
        g = _Grid(ver)
        g.place(words)
        g.mask(k)
        g.format(k, level)
        score = g.penalty()
        if best is None or score < best[0]:
            best = (score, g)
    return [row[:] for row in best[1].dark]


def to_svg(matrix: list, border: int = 4, dark: str = "#000", light: str = "#fff") -> str:
    n = len(matrix)
    cells = "".join("M%d,%dh1v1h-1z" % (x + border, y + border) for y, row in enumerate(matrix) for x, v in enumerate(row) if v)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" shape-rendering="crispEdges">'
            '<rect width="100%%" height="100%%" fill="%s"/><path d="%s" fill="%s"/></svg>') % (n + 2 * border, n + 2 * border, light, cells, dark)


def to_terminal(matrix: list, border: int = 2) -> str:
    """Two rows of modules to a line, in half blocks. The light modules are drawn (a terminal's own background is dark
    far more often than light, and a scanner reads a code either way round)."""
    n = len(matrix)
    def dark(x, y):
        return 0 <= x < n and 0 <= y < n and matrix[y][x]
    out = []
    for y in range(-border, n + border, 2):
        line = ""
        for x in range(-border, n + border):
            top, bottom = not dark(x, y), not dark(x, y + 1)          # light is the filled one
            line += "█" if top and bottom else "▀" if top else "▄" if bottom else " "
        out.append(line)
    return "\n".join(out)
