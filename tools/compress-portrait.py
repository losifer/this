#!/usr/bin/env python3
"""Compress a transparent portrait PNG into carlos.jpg + carlos-mask.png.

The About page shows the portrait as a JPEG (colour) with a separate alpha
mask applied in CSS. Together they are a fraction of the size of the
transparent PNG, and every browser supports them (macOS-encoded AVIF does
not open in Firefox).

Usage (from the repo root; needs only Python and macOS `sips`):

    python3 -I tools/compress-portrait.py path/to/photo.png

Input must be an 8-bit RGBA PNG. Writes carlos.jpg and carlos-mask.png in
the current directory.
"""
import os
import struct
import subprocess
import sys
import tempfile
import zlib

JPEG_QUALITY = 74
BLEED_PX = 10        # how far edge colours are grown into the transparent area


def read_rgba_png(path):
    d = open(path, 'rb').read()
    if d[:8] != b'\x89PNG\r\n\x1a\n':
        raise SystemExit('not a PNG')
    w, h, bd, ct = struct.unpack_from('>IIBB', d, 16)
    if (bd, ct) != (8, 6):
        raise SystemExit(f'need 8-bit RGBA PNG (got bit depth {bd}, colour type {ct})')
    i, idat = 8, b''
    while i < len(d):
        ln = struct.unpack_from('>I', d, i)[0]
        if d[i + 4:i + 8] == b'IDAT':
            idat += d[i + 8:i + 8 + ln]
        i += 12 + ln
    raw = zlib.decompress(idat)
    bpp, st = 4, w * 4
    px, prev = bytearray(), bytearray(st)
    for y in range(h):
        f = raw[y * (st + 1)]
        line = bytearray(raw[y * (st + 1) + 1:(y + 1) * (st + 1)])
        for x in range(st):
            a = line[x - bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x - bpp] if x >= bpp else 0
            if f == 1:
                line[x] = (line[x] + a) & 255
            elif f == 2:
                line[x] = (line[x] + b) & 255
            elif f == 3:
                line[x] = (line[x] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        px += line
        prev = line
    return w, h, px


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    w, h, px = read_rgba_png(sys.argv[1])
    n = w * h
    A = [px[k * 4 + 3] for k in range(n)]
    R = [px[k * 4] for k in range(n)]
    G = [px[k * 4 + 1] for k in range(n)]
    B = [px[k * 4 + 2] for k in range(n)]

    # Grow edge colours outward into the transparent area, so the JPEG
    # doesn't smear the old background into the figure's edge as a halo.
    def nbrs(k):
        x = k % w
        if x > 0: yield k - 1
        if x < w - 1: yield k + 1
        if k >= w: yield k - w
        if k < n - w: yield k + w

    filled = [a > 0 for a in A]
    frontier = [k for k in range(n) if not filled[k] and any(filled[j] for j in nbrs(k))]
    for _ in range(BLEED_PX):
        grown = []
        for k in frontier:
            s = [0, 0, 0]
            c = 0
            for j in nbrs(k):
                if filled[j]:
                    s[0] += R[j]; s[1] += G[j]; s[2] += B[j]; c += 1
            if c:
                R[k], G[k], B[k] = s[0] // c, s[1] // c, s[2] // c
                grown.append(k)
        for k in grown:
            filled[k] = True
        frontier = list({j for k in grown for j in nbrs(k) if not filled[j]})
    for k in range(n):
        if not filled[k]:
            R[k], G[k], B[k] = 40, 30, 35          # masked out anyway

    # colour -> 24-bit BMP -> JPEG via sips
    pad = (4 - (w * 3) % 4) % 4
    body = bytearray()
    for y in range(h - 1, -1, -1):
        for x in range(w):
            k = y * w + x
            body += bytes((B[k], G[k], R[k]))
        body += b'\0' * pad
    hdr = struct.pack('<2sIHHI', b'BM', 54 + len(body), 0, 0, 54) + \
        struct.pack('<IiiHHIIiiII', 40, w, h, 1, 24, 0, len(body), 2835, 2835, 0, 0)
    with tempfile.TemporaryDirectory() as tmp:
        bmp = os.path.join(tmp, 'rgb.bmp')
        open(bmp, 'wb').write(hdr + body)
        subprocess.run(['sips', '-s', 'format', 'jpeg', '-s', 'formatOptions', str(JPEG_QUALITY),
                        bmp, '--out', 'carlos.jpg'], check=True, stdout=subprocess.DEVNULL)

    # mask -> grey+alpha PNG (grey 0, alpha = the photo's alpha)
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for x in range(w):
            raw += bytes((0, A[y * w + x]))

    def chunk(t, b):
        return struct.pack('>I', len(b)) + t + b + struct.pack('>I', zlib.crc32(t + b) & 0xffffffff)

    png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 4, 0, 0, 0)) + \
        chunk(b'IDAT', zlib.compress(bytes(raw), 9)) + chunk(b'IEND', b'')
    open('carlos-mask.png', 'wb').write(png)
    print(f'wrote carlos.jpg and carlos-mask.png ({w}x{h})')


if __name__ == '__main__':
    main()
