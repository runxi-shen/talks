#!/usr/bin/env bash
# Downsample + recompress a slide-deck PDF exported from PowerPoint/Keynote.
# Text and vector art are left untouched; only oversized raster images shrink.
#
# Usage: compress-pdf.sh <in.pdf> <out.pdf> [dpi] [jpeg-quality]
#   dpi           default 150  (192 = native 1080p for a 10in-wide slide)
#   jpeg-quality  default 85
set -euo pipefail

in="${1:?usage: compress-pdf.sh <in.pdf> <out.pdf> [dpi] [jpeg-quality]}"
out="${2:?usage: compress-pdf.sh <in.pdf> <out.pdf> [dpi] [jpeg-quality]}"
dpi="${3:-150}"
quality="${4:-85}"

[ -f "$in" ] || { echo "error: no such file: $in" >&2; exit 1; }

# Ghostscript is not always on PATH; resolve it once via nix if needed.
if command -v gs >/dev/null 2>&1; then
  GS="$(command -v gs)"
elif command -v nix >/dev/null 2>&1; then
  # `nix build` can return several outputs (gs + docs); pick the one with bin/gs.
  GS=""
  for p in $(nix build --no-link --print-out-paths nixpkgs#ghostscript 2>/dev/null); do
    if [ -x "$p/bin/gs" ]; then GS="$p/bin/gs"; break; fi
  done
else
  echo "error: ghostscript not found (install gs, or make nix available)" >&2
  exit 1
fi
[ -x "$GS" ] || { echo "error: ghostscript not runnable at $GS" >&2; exit 1; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

"$GS" -dNOPAUSE -dBATCH -dSAFER -sDEVICE=pdfwrite -dCompatibilityLevel=1.7 \
  -dEmbedAllFonts=true -dSubsetFonts=true -dFastWebView=true \
  -dAutoFilterColorImages=false -dAutoFilterGrayImages=false \
  -dColorImageFilter=/DCTEncode -dGrayImageFilter=/DCTEncode \
  -dDownsampleColorImages=true -dColorImageDownsampleType=/Bicubic \
  -dColorImageResolution="$dpi" \
  -dDownsampleGrayImages=true -dGrayImageDownsampleType=/Bicubic \
  -dGrayImageResolution="$dpi" \
  -dDownsampleMonoImages=true -dMonoImageResolution=600 \
  -dColorConversionStrategy=/sRGB -dJPEGQ="$quality" \
  -sOutputFile="$tmp/out.pdf" "$in" >"$tmp/gs.log" 2>&1 || {
    echo "error: ghostscript failed; log tail:" >&2; tail -20 "$tmp/gs.log" >&2; exit 1; }

# Refuse to produce something worse than the input.
in_size=$(wc -c <"$in"); out_size=$(wc -c <"$tmp/out.pdf")
if [ "$out_size" -ge "$in_size" ]; then
  echo "note: output not smaller (${out_size} >= ${in_size}); copying input unchanged" >&2
  cp "$in" "$out"
  exit 0
fi

mv "$tmp/out.pdf" "$out"

# Sanity checks: page count, text, and links must survive.
pages_in=$(strings "$in" | grep -c '/Type */Page[^s]' || true)
pages_out=$(strings "$out" | grep -c '/Type */Page[^s]' || true)
words_in=$(pdftotext "$in" - 2>/dev/null | wc -w | tr -d ' ' || echo 0)
words_out=$(pdftotext "$out" - 2>/dev/null | wc -w | tr -d ' ' || echo 0)

printf '%-40s %6.2f MB -> %6.2f MB  (-%d%%)  %s dpi q%s\n' \
  "$(basename "$out")" \
  "$(echo "$in_size/1048576" | bc -l)" \
  "$(echo "$out_size/1048576" | bc -l)" \
  "$(( 100 - out_size * 100 / in_size ))" \
  "$dpi" "$quality"

if [ "$words_in" != "$words_out" ] && [ "$words_in" -gt 0 ]; then
  echo "warning: word count changed ($words_in -> $words_out) - inspect for dropped text" >&2
fi
