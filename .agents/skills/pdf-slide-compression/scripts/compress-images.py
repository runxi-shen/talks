#!/usr/bin/env python3
"""Recompress a slide deck's images, then verify the result.

Text, fonts, vector art and annotations are copied through untouched - content
streams are never re-encoded. That is the point: ghostscript corrupts these
decks in the font path both ways round (with -dSubsetFonts=true the ToUnicode
map breaks, 'Muñoz' -> 'Mu–oz'; with -dSubsetFonts=false glyphs stop rendering
and citations turn invisible). Touching only images avoids both.

Downsampling targets come from each image's *placed* size, recovered by walking
the content stream CTM, so a 3840x2160 image covering a third of a 10-inch
slide is reduced to what 150 dpi on that slide can actually show.

Usage: compress-images.py <in.pdf> <out.pdf> [--dpi 150] [--quality 85]
Exits 1 if verification fails, so the caller can refuse to publish.
"""
import argparse
import collections
import io
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zlib
from math import hypot

IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


# ---------------------------------------------------------------- geometry
def compose(m1, m2):
    """PDF matrix concat: result = m1 x m2."""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (a1 * a2 + b1 * c2, a1 * b2 + b1 * d2,
            c1 * a2 + d1 * c2, c1 * b2 + d1 * d2,
            e1 * a2 + f1 * c2 + e2, e1 * b2 + f1 * d2 + f2)


def walk(obj, ctm, placements, seen_forms, depth=0):
    """Record the drawn size (points) of every image, by tracking the CTM."""
    import pikepdf
    if depth > 12:
        return
    try:
        content = pikepdf.parse_content_stream(obj)
    except Exception:
        return
    stack = []
    for operands, operator in content:
        op = str(operator)
        try:
            if op == "q":
                stack.append(ctm)
            elif op == "Q":
                if stack:
                    ctm = stack.pop()
            elif op == "cm" and len(operands) == 6:
                ctm = compose(tuple(float(x) for x in operands), ctm)
            elif op == "Do" and len(operands) == 1:
                xobjs = obj.get("/Resources", {}).get("/XObject")
                if xobjs is None:
                    continue
                xobj = xobjs.get(operands[0])
                if xobj is None:
                    continue
                sub = str(xobj.get("/Subtype", ""))
                if sub == "/Image":
                    w_pt, h_pt = hypot(ctm[0], ctm[1]), hypot(ctm[2], ctm[3])
                    prev = placements.get(xobj.objgen, (0.0, 0.0))
                    placements[xobj.objgen] = (max(prev[0], w_pt), max(prev[1], h_pt))
                elif sub == "/Form" and xobj.objgen not in seen_forms:
                    seen_forms.add(xobj.objgen)
                    mat = xobj.get("/Matrix")
                    inner = tuple(float(v) for v in mat) if mat is not None else IDENTITY
                    walk(xobj, compose(inner, ctm), placements, seen_forms, depth + 1)
        except Exception:
            continue


def smask_ids(pdf):
    import pikepdf
    ids = set()
    for obj in pdf.objects:
        try:
            sm = obj.get("/SMask")
            if sm is not None and hasattr(sm, "objgen"):
                ids.add(sm.objgen)
        except Exception:
            continue
    return ids


# ------------------------------------------------------------- verification
def _pages(pdf):
    out = subprocess.run(["pdfinfo", pdf], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.startswith("Pages:"):
            return int(line.split()[1])
    return 0


def _text(pdf):
    return subprocess.run(["pdftotext", pdf, "-"], capture_output=True, text=True).stdout


def _word_boxes(pdf, page):
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
    return [(float(w.get("xMin")), float(w.get("yMin")), float(w.get("xMax")),
             float(w.get("yMax")), (w.text or "").strip())
            for pg in root.iter(ns + "page") for w in pg.iter(ns + "word")
            if (w.text or "").strip()]


def _read_ppm(path):
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


def _rendered(outdir, tag):
    files = [f for f in os.listdir(outdir) if f.startswith(tag) and f.endswith(".ppm")]
    def num(f):
        head = f[len(tag):].lstrip("-").split(".")[0]
        return int(head) if head.isdigit() else 0
    return sorted(files, key=num)


def _ink(px, w, x0, y0, x1, y1):
    """Fraction of pixels differing from the box's dominant colour."""
    counts, coords = collections.Counter(), []
    for y in range(y0, y1):
        row = y * w
        for x in range(x0, x1):
            k = (row + x) * 3
            key = (px[k] >> 4, px[k + 1] >> 4, px[k + 2] >> 4)
            counts[key] += 1
            coords.append((k, key))
    if not counts:
        return 0.0
    dom = counts.most_common(1)[0][0]
    diff = sum(1 for _, key in coords
               if abs(key[0] - dom[0]) + abs(key[1] - dom[1]) + abs(key[2] - dom[2]) > 2)
    return diff / len(coords)


def verify(src, out, dpi=100):
    """Text must be byte-identical and every word must still be painted.

    The per-word ink check is the one that matters: blanking the citations
    changed only ~0.4% of a page's pixels, so a whole-page diff cannot see it.
    Comparing each word's ink against a render of the source also avoids false
    positives for glyphs sitting on top of photos.
    """
    fails = []
    pa, pb = _pages(src), _pages(out)
    if pa != pb:
        fails.append(f"page count {pa} -> {pb}")
    ta, tb = _text(src), _text(out)
    if ta != tb:
        fails.append(f"text differs ({len(ta.split())} vs {len(tb.split())} words)")
    ca = collections.Counter(c for c in ta if ord(c) > 127)
    cb = collections.Counter(c for c in tb if ord(c) > 127)
    if ca != cb:
        fails.append(f"non-ASCII changed: {dict(ca)} -> {dict(cb)}")

    scale = dpi / 72.0
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdftoppm", "-r", str(dpi), src, os.path.join(tmp, "s")], capture_output=True)
        subprocess.run(["pdftoppm", "-r", str(dpi), out, os.path.join(tmp, "o")], capture_output=True)
        for idx, (fo, fs) in enumerate(zip(_rendered(tmp, "o"), _rendered(tmp, "s")), 1):
            wo, ho, po = _read_ppm(os.path.join(tmp, fo))
            ws, hs, ps = _read_ppm(os.path.join(tmp, fs))
            if (wo, ho) != (ws, hs):
                continue
            lost = 0
            for x0, y0, x1, y1, word in _word_boxes(out, idx):
                a, b = max(0, int(x0 * scale)), max(0, int(y0 * scale))
                c, d = min(wo - 1, int(x1 * scale) + 1), min(ho - 1, int(y1 * scale) + 1)
                if c - a < 2 or d - b < 2:
                    continue
                src_ink = _ink(ps, ws, a, b, c, d)
                if src_ink < 0.005:
                    continue
                if _ink(po, wo, a, b, c, d) < max(0.005, 0.25 * src_ink):
                    lost += 1
            if lost:
                fails.append(f"p{idx}: {lost} word(s) lost visible ink")
    return fails


# -------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--quality", type=int, default=85)
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    try:
        import pikepdf
        from PIL import Image
    except ImportError as exc:
        sys.exit(f"error: needs pikepdf and pillow ({exc})")

    pdf = pikepdf.open(args.src)
    placements, seen = {}, set()
    for page in pdf.pages:
        walk(page, IDENTITY, placements, seen)
    masks = smask_ids(pdf)

    done = kept = 0
    before_total = after_total = 0
    for obj in pdf.objects:
        try:
            if not isinstance(obj, pikepdf.Stream) or obj.get("/Subtype") != pikepdf.Name.Image:
                continue
            if obj.get("/ImageMask", False):
                continue
            w, h = int(obj.get("/Width", 0)), int(obj.get("/Height", 0))
            if w <= 1 or h <= 1:
                continue

            filt = obj.get("/Filter")
            names = [str(f) for f in filt] if isinstance(filt, pikepdf.Array) else ([str(filt)] if filt else [])
            if any(k in n for n in names for k in ("JPXDecode", "CCITTFaxDecode", "JBIG2Decode")):
                continue
            # Alpha masks stay lossless, and must be RAW pixel bytes + zlib:
            # PNG container bytes in a /FlateDecode stream decode to garbage,
            # which makes the image opaque and hides text drawn beneath it.
            is_mask = obj.objgen in masks
            w_pt, h_pt = placements.get(obj.objgen, (0.0, 0.0))
            if w_pt <= 1.0:                      # drawn nowhere we could trace
                w_pt, h_pt = 720.0, 405.0
            target_w = max(1, round(w_pt / 72.0 * args.dpi))
            target_h = max(1, round(h_pt / 72.0 * args.dpi))
            scale = min(1.0, target_w / w, target_h / h)
            new_size = (max(1, round(w * scale)), max(1, round(h * scale)))

            before = len(bytes(obj.read_raw_bytes()))
            if scale >= 0.999 and any("DCTDecode" in n for n in names):
                kept += 1                     # nothing to gain, avoid recompression
                continue

            img = pikepdf.PdfImage(obj).as_pil_image()
            if new_size != img.size:
                img = img.resize(new_size, Image.LANCZOS)
            if is_mask:
                data = zlib.compress(img.convert("L").tobytes(), 9)
                new_filter = pikepdf.Name.FlateDecode
            else:
                buf = io.BytesIO()
                if img.mode not in ("RGB", "L", "CMYK"):
                    img = img.convert("RGB")
                img.save(buf, format="JPEG", quality=args.quality, optimize=True, subsampling=1)
                new_filter = pikepdf.Name.DCTDecode
                data = buf.getvalue()
            if len(data) >= before and new_size == (w, h):
                kept += 1
                continue

            obj.write(data, filter=new_filter)
            obj.Width, obj.Height = new_size
            obj.BitsPerComponent = 8
            for key in ("/DecodeParms", "/Decode", "/SMaskInData"):
                if key in obj:
                    del obj[key]
            if is_mask:
                obj.ColorSpace = pikepdf.Name.DeviceGray
            done += 1
            before_total += before
            after_total += len(data)
            if args.verbose:
                print(f"  {w}x{h} -> {new_size[0]}x{new_size[1]}  "
                      f"{before//1024}K -> {len(data)//1024}K  placed {w_pt:.0f}x{h_pt:.0f}pt")
        except Exception as exc:
            if args.verbose:
                print(f"  skipped image: {exc}")

    pdf.save(args.dst, object_stream_mode=pikepdf.ObjectStreamMode.generate,
             compress_streams=True, linearize=True)

    in_size, out_size = os.path.getsize(args.src), os.path.getsize(args.dst)
    print(f"  {os.path.basename(args.dst)}: {in_size/1048576:.2f} -> {out_size/1048576:.2f} MB "
          f"(-{100 - out_size * 100 // in_size}%)  {done} images recompressed, {kept} untouched")

    if args.no_verify:
        return 0
    fails = verify(args.src, args.dst)
    if fails:
        print("  VERIFY FAILED:", file=sys.stderr)
        for f in fails[:10]:
            print(f"    - {f}", file=sys.stderr)
        return 1
    print("  verified: text identical, non-ASCII preserved, all words render")
    return 0


if __name__ == "__main__":
    sys.exit(main())
