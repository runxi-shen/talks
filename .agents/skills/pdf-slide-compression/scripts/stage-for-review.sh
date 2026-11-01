#!/usr/bin/env bash
# Compress deck PDFs staged in docs/ into preview/ and open a side-by-side
# review page. This script NEVER commits anything and NEVER touches docs/.
#
# Usage: stage-for-review.sh [pdf ...]      # default: every docs/*.pdf
#        DPI=192 stage-for-review.sh        # override target resolution
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
compress="$here/compress-pdf.sh"
compare="$here/make-comparison.py"
dpi="${DPI:-150}"
quality="${QUALITY:-85}"
preview="preview"

mkdir -p "$preview"

if [ "$#" -gt 0 ]; then
  pdfs=("$@")
else
  shopt -s nullglob
  pdfs=(docs/*.pdf)
  shopt -u nullglob
fi

if [ "${#pdfs[@]}" -eq 0 ]; then
  echo "error: no PDFs found in docs/" >&2
  exit 1
fi

pairs=()
for pdf in "${pdfs[@]}"; do
  [ -f "$pdf" ] || { echo "error: no such file: $pdf" >&2; exit 1; }
  base="$(basename "$pdf" .pdf)"
  comp="$preview/${base}-compressed-${dpi}dpi.pdf"
  echo "==> compressing $pdf"
  "$compress" "$pdf" "$comp" "$dpi" "$quality"
  pairs+=("$pdf" "$comp")
done

"$compare" "$preview/compare.html" "${pairs[@]}"

# Record what was staged so approve.sh can verify nothing changed underneath.
: >"$preview/.stage-manifest"
for ((i = 0; i < ${#pairs[@]}; i += 2)); do
  orig="${pairs[$i]}"
  comp="${pairs[$((i + 1))]}"
  printf '%s\t%s\t%s\n' "$(shasum -a 256 "$orig" | cut -d' ' -f1)" "$orig" "$comp" >>"$preview/.stage-manifest"
done

echo
echo "NEXT: review $preview/compare.html"
echo "  - open it and compare each deck side by side (try the photo-heavy slides)"
echo "  - zoom to 200-400% to judge sharpness"
echo "  - if it looks good: .agents/skills/pdf-slide-compression/scripts/approve.sh"
echo
echo "Nothing was committed. docs/ is untouched."
command -v open >/dev/null 2>&1 && open "$preview/compare.html" || true
