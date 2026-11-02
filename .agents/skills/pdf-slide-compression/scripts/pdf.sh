#!/usr/bin/env bash
# Slide deck pipeline: stage (lint + compress + compare) and approve (publish).
#
# Usage:
#   pdf.sh stage [NAME.pdf|--all]   decks that are new/newer than docs/ -> preview/
#   pdf.sh approve [NAME.pdf]       interactive: copy preview/ into docs/
#   pdf.sh compress IN OUT [dpi]    one-off compress + verify
#
# stage never touches docs/. approve prompts the human, and refuses without a tty.
set -euo pipefail

root="$(git rev-parse --show-toplevel)"; cd "$root"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
src=talks-original; pub=docs; prev=preview
dpi="${DPI:-150}"; quality="${QUALITY:-85}"
mkdir -p "$src" "$pub" "$prev"

# python with pikepdf+pillow: use the system one, else build a nix env once.
PY=""
if python3 -c 'import pikepdf, PIL' >/dev/null 2>&1; then
  PY="$(command -v python3)"
else
  cache="${TMPDIR:-/tmp}/pdf-compress-pyenv.path"
  if [ -s "$cache" ] && [ -x "$(cat "$cache")/bin/python3" ]; then
    PY="$(cat "$cache")/bin/python3"
  elif command -v nix >/dev/null 2>&1; then
    p="$(nix build --impure --no-link --print-out-paths --expr \
      'let f = builtins.getFlake "nixpkgs"; p = f.legacyPackages.${builtins.currentSystem};
       in p.python3.withPackages (ps: [ ps.pikepdf ps.pillow ])' 2>/dev/null | tail -1)"
    [ -n "$p" ] && [ -x "$p/bin/python3" ] && { printf '%s' "$p" >"$cache"; PY="$p/bin/python3"; }
  fi
fi
[ -n "$PY" ] || { echo "error: need python3 with pikepdf and pillow" >&2; exit 1; }

compress() { "$PY" "$here/compress-images.py" "$1" "$2" --dpi "$dpi" --quality "$quality"; }

# decks that need (re)compressing: new, or newer than their published copy
unconverted() {
  local f
  for f in "$src"/*.pdf; do
    [ -e "$f" ] || continue
    if [ ! -f "$pub/$(basename "$f")" ] || [ "$f" -nt "$pub/$(basename "$f")" ]; then
      printf '%s\n' "$f"
    fi
  done
}

write_compare() {  # $@ = src comp src comp ...
  local rows="" n i=1
  while [ "$#" -ge 2 ]; do
    rows+="    {a:'../$1', b:'$(basename "$2")', label:'$(basename "$1")'},"$'\n'
    shift 2
  done
  cat >"$prev/compare.html" <<HTML
<!doctype html><meta charset="utf-8"><title>slide review</title>
<style>
  body{margin:0;font:14px/1.4 system-ui,sans-serif}
  header{display:flex;gap:1rem;align-items:center;padding:.6rem .8rem;border-bottom:1px solid #8884}
  label{display:flex;gap:.35rem;align-items:center}
  input[type=number]{width:4.5rem}
  .row{display:grid;grid-template-columns:1fr 1fr;border-top:1px solid #8884}
  .row>div{min-width:0}
  .cap{padding:.3rem .6rem;font-size:.8rem;background:#8881}
  iframe{width:100%;height:60vh;border:0;display:block}
</style>
<header><strong>slide review</strong>
  <label>page <input id=p type=number min=1 value=1></label>
  <label>zoom <input id=z type=number min=25 step=25 value=100>%</label>
</header>
<div id=out></div>
<script>
const decks=[$'\n'$rows];
const out=document.getElementById('out'), p=document.getElementById('p'), z=document.getElementById('z');
function draw(){
  const pg=p.value||1, zm=z.value||100;
  out.innerHTML=decks.map(d=>\`<div class=row>
    <div><div class=cap>original — \${d.label}</div><iframe src="\${d.a}#page=\${pg}&zoom=\${zm}"></iframe></div>
    <div><div class=cap>compressed — \${d.b}</div><iframe src="\${d.b}#page=\${pg}&zoom=\${zm}"></iframe></div>
  </div>\`).join('');
}
[p,z].forEach(e=>e.addEventListener('change',draw)); draw();
</script>
HTML
}

cmd="${1:-}"; shift || true

case "$cmd" in
  compress)
    [ "$#" -ge 2 ] || { echo "usage: pdf.sh compress IN OUT [dpi]" >&2; exit 1; }
    [ "$#" -ge 3 ] && dpi="$3"
    compress "$1" "$2"
    ;;

  stage)
    if [ "$#" -gt 0 ] && [ "${1:-}" != "--all" ]; then
      pdfs=()
      for a in "$@"; do
        [ -f "$src/$(basename "$a")" ] || { echo "error: no $src/$(basename "$a")" >&2; exit 1; }
        pdfs+=("$src/$(basename "$a")")
      done
    elif [ "${1:-}" = "--all" ]; then
      mapfile -t pdfs < <(printf '%s\n' "$src"/*.pdf)
    else
      mapfile -t pdfs < <(unconverted)
    fi
    [ "${#pdfs[@]}" -gt 0 ] || { echo "Nothing to do: all decks in $src/ are already published (use --all to restage)."; exit 0; }

    pairs=(); flagged=0
    for f in "${pdfs[@]}"; do
      base="$(basename "$f" .pdf)"; comp="$prev/${base}-compressed-${dpi}dpi.pdf"
      echo "==> QA: $base"
      "$here/lint-slides.py" "$f" --json "$prev/${base}-lint.json" | tee "$prev/${base}-lint.txt"
      flagged=$((flagged + $("$PY" -c "import json;print(sum(1 for x in json.load(open('$prev/${base}-lint.json'))['findings'] if x['severity'] in ('high','medium')))" 2>/dev/null || echo 0)))
      echo "==> compress: $base"
      compress "$f" "$comp"
      pairs+=("$f" "$comp")
    done
    write_compare "${pairs[@]}"
    : >"$prev/.stage-manifest"
    for ((i = 0; i < ${#pairs[@]}; i += 2)); do
      printf '%s\t%s\t%s\n' "$(shasum -a 256 "${pairs[$i]}" | cut -d' ' -f1)" \
        "${pairs[$i]}" "${pairs[$((i + 1))]}" >>"$prev/.stage-manifest"
    done
    echo
    [ "$flagged" -gt 0 ] && echo "QA flagged $flagged high/medium item(s) — see preview/*-lint.txt; fix in the source deck, re-export, re-run."
    echo "Review $prev/compare.html, then: .agents/skills/pdf-slide-compression/scripts/pdf.sh approve"
    command -v open >/dev/null 2>&1 && open "$prev/compare.html" || true
    ;;

  approve)
    [ -f "$prev/.stage-manifest" ] || { echo "error: nothing staged; run: pdf.sh stage" >&2; exit 1; }
    pairs=()
    while IFS=$'\t' read -r _ s c; do [ -f "$s" ] && [ -f "$c" ] && pairs+=("$s" "$c"); done <"$prev/.stage-manifest"
    if [ "$#" -gt 0 ]; then
      keep=()
      for ((i = 0; i < ${#pairs[@]}; i += 2)); do
        for w in "$@"; do
          [ "$(basename "${pairs[$i]}")" = "$(basename "$w")" ] && keep+=("${pairs[$i]}" "${pairs[$((i + 1))]}")
        done
      done
      [ "${#keep[@]}" -gt 0 ] || { echo "error: none of those decks are staged" >&2; exit 1; }
      pairs=("${keep[@]}")
    fi
    echo "Pending:"; for ((i = 0; i < ${#pairs[@]}; i += 2)); do
      printf '  %-44s %5.2f -> %5.2f MB\n' "$(basename "${pairs[$i]}")" \
        "$(echo "$(wc -c <"${pairs[$i]}")/1048576" | bc -l)" "$(echo "$(wc -c <"${pairs[$i + 1]}")/1048576" | bc -l)"
    done
    [ -t 0 ] || { echo "error: approval needs an interactive terminal; run it yourself." >&2; exit 1; }
    echo "Have you looked at $prev/compare.html?"; printf 'Type "approved": '; read -r ans
    [ "$ans" = approved ] || { echo "aborted; $pub/ untouched."; exit 1; }
    token="$(git rev-parse --git-dir)/pdf-review-approved"; : >>"$token"
    for ((i = 0; i < ${#pairs[@]}; i += 2)); do
      dest="$pub/$(basename "${pairs[$i]}")"
      cp "${pairs[$i + 1]}" "$dest"
      grep -v " $dest\$" "$token" >"$token.tmp" 2>/dev/null || true
      mv "$token.tmp" "$token"
      printf '%s %s\n' "$(shasum -a 256 "$dest" | cut -d' ' -f1)" "$dest" >>"$token"
      printf 'approved %s\n' "$dest"
    done
    echo "Now: git add $pub/ && git commit -m 'docs(slides): publish <deck>' && git push"
    ;;

  *)
    sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
    ;;
esac
