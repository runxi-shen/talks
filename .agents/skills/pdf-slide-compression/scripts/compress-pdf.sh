#!/usr/bin/env bash
# Shrink a slide-deck PDF: recompress raster images only, leave text untouched.
#
# Ghostscript is deliberately NOT used here. It corrupts these decks in the font
# path both ways round: with -dSubsetFonts=true the ToUnicode map breaks
# ('Muñoz' -> 'Mu–oz'), and with -dSubsetFonts=false glyphs stop rendering and
# citations turn invisible. Re-encoding images only avoids both.
#
# Usage: compress-pdf.sh <in.pdf> <out.pdf> [dpi] [jpeg-quality]
#   dpi  default 150 - images are downsampled to what that resolution can show
#        on the slide, based on their placed size.
set -euo pipefail

in="${1:?usage: compress-pdf.sh <in.pdf> <out.pdf> [dpi] [quality]}"
out="${2:?usage: compress-pdf.sh <in.pdf> <out.pdf> [dpi] [quality]}"
dpi="${3:-150}"
quality="${4:-85}"

[ -f "$in" ] || { echo "error: no such file: $in" >&2; exit 1; }

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- locate a python with pikepdf + pillow --------------------------------
PY=""
if python3 -c 'import pikepdf, PIL' >/dev/null 2>&1; then
  PY="$(command -v python3)"
elif command -v nix >/dev/null 2>&1; then
  cache="${TMPDIR:-/tmp}/pdf-compress-pyenv.path"
  if [ -s "$cache" ] && [ -x "$(cat "$cache")/bin/python3" ]; then
    PY="$(cat "$cache")/bin/python3"
  else
    env_path="$(nix build --impure --no-link --print-out-paths --expr \
      'let f = builtins.getFlake "nixpkgs"; p = f.legacyPackages.${builtins.currentSystem};
       in p.python3.withPackages (ps: [ ps.pikepdf ps.pillow ])' 2>/dev/null | tail -1)"
    if [ -n "$env_path" ] && [ -x "$env_path/bin/python3" ]; then
      printf '%s' "$env_path" >"$cache"
      PY="$env_path/bin/python3"
    fi
  fi
fi

if [ -z "$PY" ]; then
  echo "error: need python3 with pikepdf and pillow (or nix to fetch them)" >&2
  exit 1
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

in_size=$(wc -c <"$in")
"$PY" "$here/compress-images.py" "$in" "$tmp/out.pdf" --dpi "$dpi" --quality "$quality"

out_size=$(wc -c <"$tmp/out.pdf")
if [ "$out_size" -ge "$in_size" ]; then
  echo "note: output not smaller (${out_size} >= ${in_size}); copying input unchanged" >&2
  cp "$in" "$out"
  exit 0
fi

mv "$tmp/out.pdf" "$out"

printf '%-40s %6.2f MB -> %6.2f MB  (-%d%%)  %s dpi q%s\n' \
  "$(basename "$out")" \
  "$(echo "$in_size/1048576" | bc -l)" \
  "$(echo "$out_size/1048576" | bc -l)" \
  "$(( 100 - out_size * 100 / in_size ))" \
  "$dpi" "$quality"

# Text, non-ASCII, per-word visibility and a coarse render diff. Must pass:
# the invisible-citation regression this replaced was invisible to every cheaper
# check, so a failure here means the output is not fit to publish.
if command -v pdftoppm >/dev/null 2>&1; then
  if ! python3 "$here/verify-pdf.py" "$in" "$out" --quiet; then
    echo "error: verification failed for $out - not fit to publish" >&2
    echo "       inspect it, then re-run stage-for-review.sh" >&2
    exit 1
  fi
  echo "  verified: text identical, non-ASCII preserved, all words render"
else
  echo "warning: pdftoppm missing, skipped visual verification" >&2
fi
