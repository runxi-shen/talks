#!/usr/bin/env python3
"""Verify a compressed deck still looks like its source.

Whole-page pixel diffs are too blunt here: ghostscript with -dSubsetFonts=false
blanked every citation, yet that only changed ~0.4% of the page's pixels - well
under any sane noise threshold. So the core check is per-text-run: every word in
the text layer must actually have visible pixels inside its own bounding box.

Usage: verify-pdf.py <source.pdf> <output.pdf> [--dpi 100]

Exit code 1 when a check fails, so callers can gate on it.

Checks:
  pages       page counts must match
  text        extracted text must be identical (byte for byte)
  nonascii    accented chars / smart quotes / dashes must survive
  visibility  no word may be painted invisibly (blank glyphs)
  render      per-page pixel diff as a coarse crash/noise detector
"""
import argparse
import collections
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


def pdfinfo_pages(pdf):
    out = subprocess.run(["pdfinfo", pdf], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.startswith("Pages:"):
            return int(line.split()[1])
    return 0


def text_of(pdf):
    return subprocess.run(["pdftotext", pdf, "-"], capture_output=True, text=True).stdout


def word_boxes(pdf, page):
    r = subprocess.run(["pdftotext", "-f", str(page), "-l", str(page), "-bbox", pdf, "-"],
                       capture_output=True, text=True)
    try:
        root = ET.fromstring(r.stdout)
    except ET.ParseError:
        try:
            root = ET.fromstring(r.stdout[r.stdout.index("<html"):])
        except (ValueError, ET.ParseError):
            return []
    ns = "{%s}" % root.tag.split("}")[0].strip("{") if "}" in root.tag else ""
    boxes = []
    for pg in root.iter(ns + "page"):
        for w in pg.iter(ns + "word"):
            t = (w.text or "").strip()
            if not t:
                continue
            boxes.append((float(w.get("xMin")), float(w.get("yMin")),
                          float(w.get("xMax")), float(w.get("yMax")), t))
    return boxes


def read_ppm(path):
    d = open(path, "rb").read()
    parts, i = [], 0
    while len(parts) < 4:
        while d[i:i + 1].isspace():
            i += 1
        j = i
        while not d[j:j + 1].isspace():
            j += 1
        parts.append(d[i:j])
        i = j
    return int(parts[1]), int(parts[2]), d[i + 1:]


def page_files(outdir, tag):
    files = [f for f in os.listdir(outdir) if f.startswith(tag) and f.endswith(".ppm")]
    def num(f):
        tail = f[len(tag):].lstrip("-")
        return int(tail.split(".")[0]) if tail.split(".")[0].isdigit() else 0
    return sorted(files, key=num)


def ink_fraction(px, w, x0, y0, x1, y1):
    """Fraction of pixels in the box that differ from the box's dominant colour."""
    counts = collections.Counter()
    coords = []
    for y in range(y0, y1):
        row = y * w
        for x in range(x0, x1):
            k = (row + x) * 3
            r, g, b = px[k], px[k + 1], px[k + 2]
            key = (r >> 4, g >> 4, b >> 4)
            counts[key] += 1
            coords.append((k, key))
    if not counts:
        return 0.0
    dominant = counts.most_common(1)[0][0]
    differing = 0
    for k, key in coords:
        # distance from dominant bucket, in 0-255 terms
        if (abs(key[0] - dominant[0]) + abs(key[1] - dominant[1])
                + abs(key[2] - dominant[2])) > 2:   # > ~32/255 combined
            differing += 1
    return differing / max(len(coords), 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--dpi", type=int, default=100)
    ap.add_argument("--min-ink", type=float, default=0.005,
                    help="below this ink fraction a word counts as invisible")
    ap.add_argument("--max-mad", type=float, default=14.0)
    ap.add_argument("--max-diff-pct", type=float, default=20.0)
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args()

    for tool in ("pdfinfo", "pdftotext", "pdftoppm"):
        if not shutil.which(tool):
            sys.exit(f"error: {tool} not found (install poppler)")

    failures = []

    pa, pb = pdfinfo_pages(args.src), pdfinfo_pages(args.out)
    if not args.quiet:
        print(f"  pages       {pa} -> {pb} {'OK' if pa == pb else 'FAIL'}")
    if pa != pb:
        failures.append(f"page count {pa} -> {pb}")

    ta, tb = text_of(args.src), text_of(args.out)
    if ta == tb:
        if not args.quiet:
            print(f"  text        identical ({len(ta.split())} words) OK")
    else:
        an, bn = ta.split(), tb.split()
        delta = [w for w in an if w not in bn][:6]
        print(f"  text        DIFFERS {len(an)} -> {len(bn)} words, e.g. {delta}")
        failures.append("extracted text differs")

    ca = collections.Counter(ch for ch in ta if ord(ch) > 127)
    cb = collections.Counter(ch for ch in tb if ord(ch) > 127)
    if ca == cb:
        if not args.quiet:
            print(f"  non-ascii   preserved ({sum(ca.values())} chars) OK")
    else:
        print(f"  non-ascii   FAIL in={dict(ca.most_common(5))} out={dict(cb.most_common(5))}")
        failures.append("non-ASCII changed")

    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdftoppm", "-r", str(args.dpi), args.out, os.path.join(tmp, "out")],
                       capture_output=True)
        subprocess.run(["pdftoppm", "-r", str(args.dpi), args.src, os.path.join(tmp, "src")],
                       capture_output=True)
        pages = page_files(tmp, "out")
        src_pages = page_files(tmp, "src")
        scale = args.dpi / 72.0

        # Differential visibility: a word only counts as broken if the SOURCE
        # shows ink in that box and the OUTPUT does not. Comparing against the
        # source removes false positives for glyphs drawn on top of photos,
        # where the box is dominated by image pixels in both files.
        invisible = []
        pre_existing = 0
        checked = 0
        for idx, (fout, fsrc) in enumerate(zip(pages, src_pages), 1):
            wo, ho, po = read_ppm(os.path.join(tmp, fout))
            ws, hs, ps = read_ppm(os.path.join(tmp, fsrc))
            if (wo, ho) != (ws, hs):
                continue
            for x0, y0, x1, y1, word in word_boxes(args.out, idx):
                ix0 = max(0, int(x0 * scale))
                iy0 = max(0, int(y0 * scale))
                ix1 = min(wo - 1, int(x1 * scale) + 1)
                iy1 = min(ho - 1, int(y1 * scale) + 1)
                if ix1 - ix0 < 2 or iy1 - iy0 < 2:
                    continue
                checked += 1
                src_ink = ink_fraction(ps, ws, ix0, iy0, ix1, iy1)
                out_ink = ink_fraction(po, wo, ix0, iy0, ix1, iy1)
                if src_ink < args.min_ink:
                    continue                       # nothing visible to lose
                if out_ink < max(args.min_ink, 0.25 * src_ink):
                    invisible.append((idx, word, src_ink, out_ink))

        if invisible:
            print(f"  visibility  FAIL {len(invisible)} of {checked} words lost visible ink")
            for pg, word, si, oi in invisible[:8]:
                print(f"                p{pg}: {word!r} source={si*100:.1f}% -> output={oi*100:.2f}%")
            if len(invisible) > 8:
                print(f"                ... and {len(invisible)-8} more")
            failures.append(f"{len(invisible)} text runs went invisible")
        elif not args.quiet:
            print(f"  visibility  all {checked} words render OK")

        subprocess.run(["pdftoppm", "-r", str(args.dpi), args.src, os.path.join(tmp, "src2")],
                       capture_output=True)
        fa = page_files(tmp, "src2")
        worst = (0.0, 0.0, "")
        for f1, f2 in zip(fa, pages):
            w1, h1, a = read_ppm(os.path.join(tmp, f1))
            w2, h2, b = read_ppm(os.path.join(tmp, f2))
            if (w1, h1) != (w2, h2):
                failures.append(f"{f1[:-4]}: render size differs")
                continue
            n = min(len(a), len(b))
            tot = big = cnt = 0
            for k in range(0, n, 3):
                d = abs(a[k] - b[k])
                tot += d
                if d > 32:
                    big += 1
                cnt += 1
            mad = tot / max(cnt, 1)
            pct = 100.0 * big / max(cnt, 1)
            if mad > worst[0]:
                worst = (mad, pct, f1)
            if mad > args.max_mad or pct > args.max_diff_pct:
                failures.append(f"{f1[:-4]}: render differs (mad={mad:.1f}, {pct:.1f}%)")
        if not args.quiet:
            print(f"  render      worst page {worst[2][:-4]}: mad={worst[0]:.2f}, "
                  f"{worst[1]:.1f}% pixels differ")

    if failures:
        print("\n  VERIFY FAILED:")
        for f in failures[:12]:
            print(f"    - {f}")
        return 1
    if not args.quiet:
        print("  result      all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
