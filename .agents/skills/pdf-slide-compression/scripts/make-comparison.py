#!/usr/bin/env python3
"""Generate a side-by-side PDF comparison page (original vs compressed).

Usage: make-comparison.py <out.html> <orig.pdf> <compressed.pdf> [<orig2> <comp2> ...]

Both PDFs for a pair must have the same page count. Paths are written into the
HTML relative to the output file's directory.
"""
import html
import os
import re
import subprocess
import sys


def page_count(path):
    try:
        out = subprocess.run(["pdfinfo", path], capture_output=True, text=True, check=True).stdout
        m = re.search(r"^Pages:\s+(\d+)", out, re.M)
        if m:
            return int(m.group(1))
    except (OSError, subprocess.CalledProcessError):
        pass
    data = open(path, "rb").read()
    return max(1, len(re.findall(rb"/Type\s*/Page[^s]", data)))


def size_mb(path):
    return os.path.getsize(path) / 1048576


def rel(path, base_dir):
    return os.path.relpath(os.path.abspath(path), os.path.abspath(base_dir))


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>PDF compression review</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ margin: 0; font: 14px/1.4 system-ui, -apple-system, sans-serif; }}
  header {{
    display: flex; gap: 1rem; align-items: center; flex-wrap: wrap;
    padding: .6rem .8rem; border-bottom: 1px solid #8884;
  }}
  header h1 {{ font-size: .95rem; margin: 0 1rem 0 0; font-weight: 600; }}
  label {{ display: flex; gap: .35rem; align-items: center; }}
  input[type=number] {{ width: 4.5rem; }}
  .note {{ padding: .4rem .8rem; font-size: .8rem; background: #f5c54222; border-bottom: 1px solid #8883; }}
  .files {{ display: grid; grid-template-columns: 1fr 1fr; height: calc(100vh - 6.2rem); }}
  .files > section {{ display: flex; flex-direction: column; min-width: 0; }}
  .files > section + section {{ border-left: 1px solid #8884; }}
  .cap {{ padding: .35rem .6rem; font-size: .8rem; background: #8881; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .cap b {{ font-weight: 600; }}
  iframe {{ flex: 1; width: 100%; border: 0; }}
</style>
</head>
<body>
<header>
  <h1>Compression review</h1>
  <label>Deck <select id="deck">{options}</select></label>
  <label>Page <input id="page" type="number" min="1" value="1"></label>
  <label>Zoom <input id="zoom" type="number" min="25" max="800" step="25" value="100">%</label>
</header>
<div class="note">Inspect photo-heavy slides and any figure with fine detail. Zoom to 200&ndash;400% to judge sharpness. Text and vector art should look identical.</div>
<div class="files">
  <section>
    <div class="cap"><b>Original</b> &mdash; <span id="lname"></span></div>
    <iframe id="left" title="Original PDF"></iframe>
  </section>
  <section>
    <div class="cap"><b>Compressed</b> &mdash; <span id="rname"></span></div>
    <iframe id="right" title="Compressed PDF"></iframe>
  </section>
</div>
<script>
  const decks = {decks};
  const deck = document.getElementById('deck');
  const page = document.getElementById('page');
  const zoom = document.getElementById('zoom');

  function render() {{
    const d = decks[deck.value];
    page.max = d.pages;
    const p = Math.min(Math.max(1, parseInt(page.value, 10) || 1), d.pages);
    const z = parseInt(zoom.value, 10) || 100;
    const hash = `#page=${{p}}&zoom=${{z}}`;
    document.getElementById('left').src = d.orig + hash;
    document.getElementById('right').src = d.comp + hash;
    document.getElementById('lname').textContent = `${{d.orig}} (${{d.origMb}} MB)`;
    document.getElementById('rname').textContent = `${{d.comp}} (${{d.compMb}} MB, -${{d.saved}}%)`;
  }}

  [deck, page, zoom].forEach(el => el.addEventListener('change', render));
  render();
</script>
</body>
</html>
"""


def main(argv):
    if len(argv) < 4 or (len(argv) - 2) % 2:
        sys.exit(__doc__)

    out = argv[1]
    pairs = [(argv[i], argv[i + 1]) for i in range(2, len(argv), 2)]
    base_dir = os.path.dirname(os.path.abspath(out))

    entries = []
    options = []
    for idx, (orig, comp) in enumerate(pairs):
        for p in (orig, comp):
            if not os.path.exists(p):
                sys.exit(f"error: no such file: {p}")
        pages = page_count(orig)
        comp_pages = page_count(comp)
        if comp_pages != pages:
            print(f"warning: {comp} has {comp_pages} pages, {orig} has {pages}", file=sys.stderr)
        om, cm = size_mb(orig), size_mb(comp)
        name = os.path.basename(orig)
        entries.append(
            "  %d: {orig: %s, comp: %s, pages: %d, origMb: '%.2f', compMb: '%.2f', saved: %d}"
            % (
                idx,
                repr(rel(orig, base_dir)).replace("'", '"'),
                repr(rel(comp, base_dir)).replace("'", '"'),
                pages,
                om,
                cm,
                round(100 - cm * 100 / om),
            )
        )
        options.append('<option value="%d">%s</option>' % (idx, html.escape(name)))

    html_out = TEMPLATE.format(
        options="".join(options),
        decks="{\n" + ",\n".join(entries) + "\n}",
    )
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html_out)
    print(f"wrote {out} ({len(pairs)} deck{'s' if len(pairs) != 1 else ''})")


if __name__ == "__main__":
    main(sys.argv)
