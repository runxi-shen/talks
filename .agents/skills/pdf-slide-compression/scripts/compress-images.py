#!/usr/bin/env python3
"""Compress raster images only; preserve text/fonts, then verify before saving.

Ghostscript rewrote these decks' fonts and broke citations. Do not use it here.
Requires pikepdf, Pillow and Poppler (pdfinfo, pdftotext, pdftoppm).
"""
import argparse
import collections
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from math import hypot

IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def compose(m1, m2):
    a, b, c, d, e, f = m1
    g, h, i, j, k, l = m2
    return (a*g+b*i, a*h+b*j, c*g+d*i, c*h+d*j, e*g+f*i+k, e*h+f*j+l)


def walk(obj, ctm, placements, ancestors=(), resources=None):
    """Measure every placement, including shared Forms drawn at different scales."""
    import pikepdf
    resources = obj.get('/Resources', resources)
    if resources is None or len(ancestors) > 20:
        return
    try:
        content = pikepdf.parse_content_stream(obj)
    except pikepdf.PdfError:
        return  # Unmeasured images are left untouched, never guessed at slide size.
    stack = []
    for operands, operator in content:
        op = str(operator)
        if op == 'q':
            stack.append(ctm)
        elif op == 'Q' and stack:
            ctm = stack.pop()
        elif op == 'cm':
            # Some PDFium exports contain malformed numbers. Do not guess a
            # scale for this graphics state; leave affected images untouched.
            ctm = compose(tuple(float(x) for x in operands), ctm) if ctm is not None and len(operands) == 6 else None
        elif op == 'Do':
            xobj = resources.get('/XObject', {}).get(operands[0])
            if xobj is None:
                continue
            if xobj.get('/Subtype') == pikepdf.Name.Image:
                prev = placements.get(xobj.objgen, (0.0, 0.0))
                placements[xobj.objgen] = None if ctm is None or prev is None else (
                    max(prev[0], hypot(*ctm[:2])), max(prev[1], hypot(*ctm[2:4])))
            elif xobj.get('/Subtype') == pikepdf.Name.Form and xobj.objgen not in ancestors:
                matrix = tuple(float(x) for x in xobj.get('/Matrix', IDENTITY))
                inner = compose(matrix, ctm) if ctm is not None and len(matrix) == 6 else None
                walk(xobj, inner, placements,
                     ancestors + (xobj.objgen,), resources)


def command(*args):
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout


def pages(pdf):
    for line in command('pdfinfo', str(pdf)).splitlines():
        if line.startswith('Pages:') and int(line.split()[1]) > 0:
            return int(line.split()[1])
    raise ValueError(f'Cannot determine page count: {pdf}')


def word_boxes(pdf, page):
    root = ET.fromstring(command('pdftotext', '-f', str(page), '-l', str(page),
                                 '-bbox', str(pdf), '-'))
    if sum(node.tag.rsplit('}', 1)[-1] == 'page' for node in root.iter()) != 1:
        raise ValueError(f'Missing page geometry: {pdf}, p{page}')
    words = []
    for node in root.iter():
        if node.tag.rsplit('}', 1)[-1] == 'word':
            words.append(tuple(float(node.get(k)) for k in ('xMin', 'yMin', 'xMax', 'yMax')))
    return words


def ink(pixels, width, box):
    """Contrast against the dominant colour; works for dark or light lettering."""
    x0, y0, x1, y1 = box
    counts = collections.Counter()
    for y in range(y0, y1):
        for x in range(x0, x1):
            k = (y * width + x) * 3
            counts[tuple(c >> 4 for c in pixels[k:k+3])] += 1
    if not counts:
        return 0.0
    dominant = counts.most_common(1)[0][0]
    return sum(n for colour, n in counts.items()
               if sum(abs(a-b) for a, b in zip(colour, dominant)) > 2) / sum(counts.values())


def verify(src, out, dpi=100):
    """Fail closed: missing tools, failed renders and malformed output are errors.

    shortcut: per-word contrast is a heuristic, not visual proof; human review
    remains mandatory for figures, colours and fine-detail image quality.
    """
    from PIL import Image
    failures = []
    count = pages(src)
    if pages(out) != count:
        return ['page count changed']
    # Exact text equality also covers Unicode, punctuation and reading order.
    if command('pdftotext', str(src), '-') != command('pdftotext', str(out), '-'):
        return ['extracted text changed']
    scale = dpi / 72
    with tempfile.TemporaryDirectory() as tmp:
        for page in range(1, count + 1):
            rendered = []
            for name, pdf in (('source', src), ('output', out)):
                prefix = str(Path(tmp) / name)
                command('pdftoppm', '-f', str(page), '-l', str(page), '-singlefile',
                        '-r', str(dpi), str(pdf), prefix)
                with Image.open(prefix + '.ppm') as image:
                    rendered.append((image.size, image.convert('RGB').tobytes()))
            (size, original), (other_size, result) = rendered
            if size != other_size:
                failures.append(f'p{page}: render dimensions changed')
                continue
            width, height = size
            lost = 0
            for x0, y0, x1, y1 in word_boxes(src, page):
                box = (max(0, int(x0 * scale)), max(0, int(y0 * scale)),
                       min(width, int(x1 * scale) + 1), min(height, int(y1 * scale) + 1))
                if box[2] - box[0] < 2 or box[3] - box[1] < 2:
                    continue
                before = ink(original, width, box)
                if before >= 0.005 and ink(result, width, box) < max(0.005, before * 0.25):
                    lost += 1
            if lost:
                failures.append(f'p{page}: {lost} word(s) lost visible ink')
    return failures


def compress(src, dst, dpi=150, quality=85):
    import pikepdf
    from PIL import Image
    src, dst = Path(src), Path(dst)
    if src.resolve() == dst.resolve():
        raise ValueError('Source and output must be different files')
    if dpi <= 0 or not 1 <= quality <= 100:
        raise ValueError('DPI must be positive; JPEG quality must be 1–100')
    for tool in ('pdfinfo', 'pdftotext', 'pdftoppm'):
        if not shutil.which(tool):
            raise RuntimeError(f'{tool} is required (install Poppler)')

    with pikepdf.open(src) as pdf:
        placements, masks = {}, set()
        for page in pdf.pages:
            unit = float(page.obj.get('/UserUnit', 1))
            walk(page, (unit, 0, 0, unit, 0, 0), placements)
        for obj in pdf.objects:
            if isinstance(obj, pikepdf.Stream) and obj.get('/Subtype') == pikepdf.Name.Image:
                mask = obj.get('/SMask')
                if isinstance(mask, pikepdf.Stream):
                    masks.add(mask.objgen)

        changed = skipped = 0
        for obj in pdf.objects:
            if not isinstance(obj, pikepdf.Stream) or obj.get('/Subtype') != pikepdf.Name.Image:
                continue
            # Keep alpha masks and unusual colour mappings exactly as exported.
            # Their byte savings aren't worth risking transparency or colour bugs.
            if (obj.objgen in masks or obj.get('/ImageMask', False)
                    or any(k in obj for k in ('/Decode', '/Mask', '/SMaskInData'))
                    or placements.get(obj.objgen) is None):
                continue
            colour = obj.get('/ColorSpace')
            channels = {pikepdf.Name.DeviceRGB: 'RGB', pikepdf.Name.DeviceGray: 'L'}
            if isinstance(colour, pikepdf.Array) and colour[0] == pikepdf.Name.ICCBased:
                mode = {1: 'L', 3: 'RGB'}.get(int(colour[1].get('/N', 0)))
            else:
                mode = channels.get(colour) if isinstance(colour, pikepdf.Name) else None
            if mode is None:
                continue
            filt = obj.get('/Filter')
            filters = list(filt) if isinstance(filt, pikepdf.Array) else [filt]
            if any(f not in (None, pikepdf.Name.FlateDecode, pikepdf.Name.DCTDecode) for f in filters):
                continue
            w, h = int(obj.Width), int(obj.Height)
            wp, hp = placements[obj.objgen]
            scale = min(1.0, wp * dpi / (72*w), hp * dpi / (72*h))
            if scale >= 0.999 and pikepdf.Name.DCTDecode in filters:
                continue
            try:
                image = pikepdf.PdfImage(obj).as_pil_image()
                if image.mode == mode + 'A':
                    image = image.convert(mode)  # Alpha is preserved separately in /SMask.
                if image.mode != mode:
                    skipped += 1
                    continue
                image = image.resize((max(1, round(w*scale)), max(1, round(h*scale))), Image.Resampling.LANCZOS)
                buffer = io.BytesIO()
                image.save(buffer, format='JPEG', quality=quality, optimize=True, subsampling=1)
                data = buffer.getvalue()
            except (OSError, ValueError, NotImplementedError):
                skipped += 1
                continue
            if len(data) >= len(obj.read_raw_bytes()):
                continue
            obj.write(data, filter=pikepdf.Name.DCTDecode)
            obj.Width, obj.Height = image.size
            obj.BitsPerComponent = 8
            if '/DecodeParms' in obj:
                del obj['/DecodeParms']
            changed += 1

        # Only replace the destination after successful verification. A failed run
        # cannot overwrite a reviewed preview or damage an existing published file.
        with tempfile.TemporaryDirectory(dir=dst.parent) as tmp:
            candidate = Path(tmp) / 'compressed.pdf'
            pdf.save(candidate, object_stream_mode=pikepdf.ObjectStreamMode.generate,
                     compress_streams=True, linearize=True)
            if candidate.stat().st_size >= src.stat().st_size:
                shutil.copyfile(src, candidate)
            failures = verify(src, candidate)
            if failures:
                raise ValueError('Verification failed: ' + '; '.join(failures))
            os.replace(candidate, dst)
    print(f'{dst.name}: {src.stat().st_size/1048576:.2f} → {dst.stat().st_size/1048576:.2f} MiB; '
          f'{changed} images compressed, {skipped} unsupported images left alone')
    print('Verified: exact text, page count and text-visibility check passed. Review figures manually.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('src')
    parser.add_argument('dst')
    parser.add_argument('--dpi', type=int, default=150)
    parser.add_argument('--quality', type=int, default=85)
    args = parser.parse_args()
    try:
        compress(args.src, args.dst, args.dpi, args.quality)
    except (ImportError, OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'error: {exc}\n')


if __name__ == '__main__':
    main()
