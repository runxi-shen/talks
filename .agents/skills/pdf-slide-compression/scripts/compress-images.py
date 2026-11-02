#!/usr/bin/env python3
"""Shrink a slide-deck PDF by recompressing ONLY its raster images.

Text, fonts, vector art and annotations are copied through untouched - content
streams are never re-encoded. That is the whole point: ghostscript corrupts
these decks in the font path both ways round. With -dSubsetFonts=true the
ToUnicode map breaks ('Muñoz' -> 'Mu–oz'); with -dSubsetFonts=false some glyphs
stop rendering entirely, so citations vanish. Leaving text alone avoids both.

Downsampling uses the *placed* size, recovered by walking the content stream
and tracking the CTM, so a 3840x2160 image covering a third of a 10-inch slide
is reduced to what 150 dpi on that slide can actually show.

Usage: compress-images.py <in.pdf> <out.pdf> [--dpi 150] [--quality 85]
"""
import argparse
import io
import sys
from math import hypot


IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def compose(m1, m2):
    """PDF matrix concat: result = m1 x m2 (apply m1, then m2's frame)."""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    )


def resolve(resources, name, depth=0):
    """Look up a named XObject, following indirect refs."""
    try:
        xobjs = resources.get("/XObject")
        if xobjs is None:
            return None
        return xobjs.get(name)
    except Exception:
        return None


def walk(obj, ctm, placements, seen_forms, depth=0):
    """Record the rendered size (in points) of every image drawn."""
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
                m = tuple(float(x) for x in operands)
                ctm = compose(m, ctm)
            elif op == "Do" and len(operands) == 1:
                name = operands[0]
                xobj = resolve(obj.get("/Resources", {}), name)
                if xobj is None:
                    continue
                sub = str(xobj.get("/Subtype", ""))
                if sub == "/Image":
                    # unit square transformed by ctm -> drawn size in points
                    w_pt = hypot(ctm[0], ctm[1])
                    h_pt = hypot(ctm[2], ctm[3])
                    key = id(xobj.objgen) if hasattr(xobj, "objgen") else None
                    key = xobj.objgen if hasattr(xobj, "objgen") else key
                    prev = placements.get(key, (0.0, 0.0))
                    placements[key] = (max(prev[0], w_pt), max(prev[1], h_pt))
                elif sub == "/Form":
                    fkey = xobj.objgen if hasattr(xobj, "objgen") else id(xobj)
                    if fkey in seen_forms:
                        continue
                    seen_forms.add(fkey)
                    mat = xobj.get("/Matrix")
                    inner = tuple(float(v) for v in mat) if mat is not None else IDENTITY
                    walk(xobj, compose(inner, ctm), placements, seen_forms, depth + 1)
        except Exception:
            continue


def collect_smask_ids(pdf):
    """Object gens referenced by any /SMask - handled as masks, never JPEG'd."""
    ids = set()
    for obj in pdf.objects:
        try:
            if isinstance(obj, __import__("pikepdf").Dictionary):
                sm = obj.get("/SMask")
                if sm is not None and hasattr(sm, "objgen"):
                    ids.add(sm.objgen)
        except Exception:
            continue
    return ids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--quality", type=int, default=85)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    try:
        import pikepdf
        from PIL import Image
    except ImportError as exc:
        sys.exit(f"error: missing python deps ({exc}); need pikepdf and pillow")

    pdf = pikepdf.open(args.src)

    placements = {}
    seen_forms = set()
    for page in pdf.pages:
        walk(page, IDENTITY, placements, seen_forms)

    smask_ids = collect_smask_ids(pdf)
    stats = dict(images=0, done=0, kept=0, skipped=0, before=0, after=0)

    for obj in pdf.objects:
        try:
            if not isinstance(obj, pikepdf.Stream):
                continue
            if obj.get("/Subtype") != pikepdf.Name.Image:
                continue
            if obj.get("/ImageMask", False):
                continue
            w = int(obj.get("/Width", 0))
            h = int(obj.get("/Height", 0))
            if w <= 1 or h <= 1:
                continue
            stats["images"] += 1

            filt = obj.get("/Filter")
            names = [str(f) for f in filt] if isinstance(filt, pikepdf.Array) else ([str(filt)] if filt else [])
            if any(("JPXDecode" in n or "CCITTFaxDecode" in n or "JBIG2Decode" in n) for n in names):
                stats["skipped"] += 1
                continue
            is_mask_only = obj.objgen in smask_ids

            # Target pixels from placed size; fall back to a 10in-wide slide.
            w_pt, h_pt = placements.get(obj.objgen, (0.0, 0.0))
            if w_pt <= 1.0:
                w_pt, h_pt = 720.0, 405.0
            target_w = max(1, round(w_pt / 72.0 * args.dpi))
            target_h = max(1, round(h_pt / 72.0 * args.dpi))
            scale = min(1.0, target_w / w, target_h / h)
            new_size = (max(1, round(w * scale)), max(1, round(h * scale)))

            before = len(bytes(obj.read_raw_bytes()))
            already_jpeg = any("DCTDecode" in n for n in names)
            if scale >= 0.999 and already_jpeg:
                stats["kept"] += 1          # no resize needed, avoid generation loss
                continue

            img = pikepdf.PdfImage(obj).as_pil_image()
            if new_size != img.size:
                img = img.resize(new_size, Image.LANCZOS)

            buf = io.BytesIO()
            if is_mask_only:
                # keep masks lossless; JPEG on alpha edges produces halos
                if img.mode not in ("L", "1"):
                    img = img.convert("L")
                img.save(buf, format="PNG", optimize=True)
                new_filter = pikepdf.Name.FlateDecode
            else:
                if img.mode not in ("RGB", "L", "CMYK"):
                    img = img.convert("RGB")
                img.save(buf, format="JPEG", quality=args.quality,
                         optimize=True, subsampling=1)
                new_filter = pikepdf.Name.DCTDecode
            data = buf.getvalue()

            if len(data) >= before and new_size == (w, h):
                stats["kept"] += 1          # nothing gained
                continue

            obj.write(data, filter=new_filter)
            obj.Width, obj.Height = new_size
            obj.BitsPerComponent = 8
            for key in ("/DecodeParms", "/Decode", "/SMaskInData"):
                if key in obj:
                    del obj[key]
            if is_mask_only:
                obj.ColorSpace = pikepdf.Name.DeviceGray
            stats["done"] += 1
            stats["before"] += before
            stats["after"] += len(data)
            if args.verbose:
                print(f"  {w}x{h} -> {new_size[0]}x{new_size[1]}  "
                      f"{before/1024:.0f}K -> {len(data)/1024:.0f}K  "
                      f"placed {w_pt:.0f}x{h_pt:.0f}pt  mask={is_mask_only}")
        except Exception as exc:
            stats["skipped"] += 1
            if args.verbose:
                print(f"  skipped: {exc}")

    pdf.save(args.dst, object_stream_mode=pikepdf.ObjectStreamMode.generate,
             compress_streams=True, linearize=True)

    print(f"  images: {stats['images']} found, {stats['done']} recompressed, "
          f"{stats['kept']} left alone, {stats['skipped']} skipped")
    if stats["before"]:
        print(f"  image data: {stats['before']/1048576:.2f} MB -> {stats['after']/1048576:.2f} MB")


if __name__ == "__main__":
    main()
