#!/usr/bin/env bash
# Usage: pdf.sh stage [NAME.pdf|--all] | approve [NAME.pdf] | compress IN OUT [dpi]
# stage leaves docs/ untouched; approve requires human inspection and a terminal.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$(git rev-parse --show-toplevel)"
src=talks-original; pub=docs; prev=preview
manifest="$prev/.stage-manifest"
dpi="${DPI:-150}"; quality="${QUALITY:-85}"

fail() { echo "error: $*" >&2; exit 1; }
hash() { shasum -a 256 "$1" | cut -d' ' -f1; }
name_ok() { [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*\.pdf$ ]]; }

compress() {
  local py=python3 env_path
  if ! "$py" -c 'import pikepdf, PIL' >/dev/null 2>&1; then
    command -v nix >/dev/null || fail "install pikepdf and Pillow for python3 (or install Nix)"
    env_path="$(nix build --impure --no-link --print-out-paths --expr \
      'let f = builtins.getFlake "nixpkgs"; p = f.legacyPackages.${builtins.currentSystem};
       in p.python3.withPackages (ps: [ ps.pikepdf ps.pillow ])' | tail -1)"
    py="$env_path/bin/python3"
  fi
  "$py" "$here/compress-images.py" "$1" "$2" --dpi "$dpi" --quality "$quality"
}

write_compare() {
  python3 - "$prev/compare.html" "$@" <<'PY'
import html, pathlib, sys, urllib.parse
out, *pairs = sys.argv[1:]
rows = []
for source, compressed in zip(pairs[::2], pairs[1::2]):
    cells = []
    for label, path in [('Original', '../' + source), ('Compressed', pathlib.Path(compressed).name)]:
        url = html.escape(urllib.parse.quote(path))
        caption = html.escape(f'{label} — {pathlib.Path(source).name}')
        cells.append(f'<section><p>{caption}</p><iframe title="{caption}" data-src="{url}"></iframe></section>')
    rows.append('<div class="row">' + ''.join(cells) + '</div>')
pathlib.Path(out).write_text('''<!doctype html><html lang="en"><meta charset="utf-8">
<title>Slide review</title><style>
body{margin:0;font:14px system-ui}header{padding:1rem}input{width:5rem}
.row{display:grid;grid-template-columns:1fr 1fr}section{min-width:0}
p{padding:0 .5rem}iframe{width:100%;height:75vh;border:1px solid #ccc;box-sizing:border-box}
</style><header><b>Compare originals and compressed slides</b>
<label>Page <input id="page" type="number" min="1" value="1"></label>
<label>Zoom % <input id="zoom" type="number" min="25" max="800" value="100"></label>
<p>Read preview/*-lint.txt too. Compression checks do not replace visual review.</p></header>
''' + ''.join(rows) + '''<script>
const page = document.getElementById('page'), zoom = document.getElementById('zoom');
function draw() {
  const p = Math.max(1, Number(page.value) || 1);
  const z = Math.min(800, Math.max(25, Number(zoom.value) || 100));
  document.querySelectorAll('iframe').forEach(f => f.src = f.dataset.src + '#page=' + p + '&zoom=' + z);
}
page.addEventListener('change', draw); zoom.addEventListener('change', draw); draw();
</script></html>''', encoding='utf-8')
PY
}

check_review() {
  local i
  for ((i=0; i<${#sources[@]}; i++)); do
    [ -f "${sources[$i]}" ] && [ -f "${outputs[$i]}" ] || fail "review files missing; run stage again"
    [ "$(hash "${sources[$i]}")" = "${source_hashes[$i]}" ] || fail "source changed; run stage again"
    [ "$(hash "${outputs[$i]}")" = "${output_hashes[$i]}" ] || fail "preview changed; run stage again"
  done
}

cmd="${1:-help}"; [ "$#" -eq 0 ] || shift
case "$cmd" in
  compress)
    [ "$#" -ge 2 ] && [ "$#" -le 3 ] || fail "usage: pdf.sh compress IN OUT [dpi]"
    dpi="${3:-$dpi}"
    compress "$1" "$2"
    ;;
  stage)
    mkdir -p "$src" "$prev"
    # Failed or no-op staging must never leave an older batch approvable.
    rm -f "$manifest" "$manifest.tmp" "$prev/compare.html"
    pdfs=()
    if [ "$#" -gt 0 ] && [ "$1" != --all ]; then
      for arg in "$@"; do
        name="$(basename "$arg")"
        name_ok "$name" || fail "use a stable PDF filename without spaces: $name"
        [ -f "$src/$name" ] || fail "missing $src/$name"
        pdfs+=("$src/$name")
      done
    else
      [ "$#" -eq 0 ] || { [ "$#" -eq 1 ] && [ "$1" = --all ]; } || fail "usage: pdf.sh stage [NAME.pdf|--all]"
      for file in "$src"/*.pdf; do
        [ -f "$file" ] || continue
        name="$(basename "$file")"
        name_ok "$name" || fail "use a stable PDF filename without spaces: $name"
        if [ "${1:-}" = --all ] || [ ! -f "$pub/$name" ] || [ "$file" -nt "$pub/$name" ]; then
          pdfs+=("$file")
        fi
      done
    fi
    [ "${#pdfs[@]}" -gt 0 ] || { echo "Nothing pending; use stage --all to restage existing exports."; exit 0; }
    pairs=()
    for file in "${pdfs[@]}"; do
      base="$(basename "$file" .pdf)"; output="$prev/$base-compressed.pdf"
      source_hash="$(hash "$file")"
      echo "==> QA: $base"
      python3 "$here/lint-slides.py" "$file" | tee "$prev/$base-lint.txt"
      compress "$file" "$output"
      [ "$(hash "$file")" = "$source_hash" ] || fail "source changed during compression; restage"
      printf '%s\t%s\t%s\t%s\n' "$source_hash" "$(hash "$output")" "$file" "$output" >>"$manifest.tmp"
      pairs+=("$file" "$output")
    done
    write_compare "${pairs[@]}"
    mv "$manifest.tmp" "$manifest"
    echo "Review preview/compare.html AND preview/*-lint.txt; then run: $0 approve"
    if command -v open >/dev/null; then open "$prev/compare.html" || true; fi
    ;;
  approve)
    [ -s "$manifest" ] && [ -f "$prev/compare.html" ] || fail "nothing staged; run stage first"
    sources=(); outputs=(); source_hashes=(); output_hashes=()
    while IFS=$'\t' read -r sh oh source output; do
      name="$(basename "$source")"
      name_ok "$name" && [ "$source" = "$src/$name" ] && [ "$output" = "$prev/${name%.pdf}-compressed.pdf" ] || fail "invalid review manifest; restage"
      selected=0
      if [ "$#" -eq 0 ]; then selected=1; else
        for arg in "$@"; do [ "$(basename "$arg")" != "$name" ] || selected=1; done
      fi
      if [ "$selected" -eq 1 ]; then
        sources+=("$source"); outputs+=("$output"); source_hashes+=("$sh"); output_hashes+=("$oh")
      fi
    done <"$manifest"
    [ "${#sources[@]}" -gt 0 ] || fail "none of those decks are staged"
    check_review
    printf 'Pending: %s\n' "${sources[@]}"
    [ -t 0 ] || fail "approval needs an interactive terminal; run it yourself"
    printf 'After inspecting the comparison AND QA reports, type "approved": '
    read -r answer
    [ "$answer" = approved ] || fail "aborted; docs/ untouched"
    check_review
    mkdir -p "$pub"
    token="$(git rev-parse --git-path pdf-review-approved)"; touch "$token"
    for ((i=0; i<${#sources[@]}; i++)); do
      dest="$pub/$(basename "${sources[$i]}")"
      cp "${outputs[$i]}" "$dest"
      printf '%s\t%s\n' "${output_hashes[$i]}" "$dest" >>"$token"
      echo "Approved: $dest"
    done
    echo "Update docs/index.html slide counts/sizes, then commit and push. Sources stay in talks-original/."
    ;;
  help|-h|--help)
    echo "Usage: $0 stage [NAME.pdf|--all] | approve [NAME.pdf] | compress IN OUT [dpi]"
    ;;
  *) fail "unknown command: $cmd" ;;
esac
