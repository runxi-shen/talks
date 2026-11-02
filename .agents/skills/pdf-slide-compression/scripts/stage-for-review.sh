#!/usr/bin/env bash
# Compress unconverted deck exports from talks-original/ into preview/ and open a
# side-by-side review page. Runs a text/layout QA pass first.
#
# This script NEVER commits and NEVER writes to docs/.
#
# Usage:
#   stage-for-review.sh                 # every deck in talks-original/ that is new
#                                       # or newer than its docs/ counterpart
#   stage-for-review.sh NAME.pdf        # one deck (from talks-original/)
#   stage-for-review.sh --all           # restage everything, converted or not
#   DPI=192 stage-for-review.sh         # override target resolution
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
compress="$here/compress-pdf.sh"
lint="$here/lint-slides.py"
compare="$here/make-comparison.py"
dpi="${DPI:-150}"
quality="${QUALITY:-85}"
src_dir="talks-original"
pub_dir="docs"
preview="preview"

force_all=0
wanted=()
for arg in "$@"; do
  case "$arg" in
    --all | --force) force_all=1 ;;
    *) wanted+=("$arg") ;;
  esac
done

[ -d "$src_dir" ] || { echo "error: $src_dir/ not found" >&2; exit 1; }
mkdir -p "$src_dir" "$pub_dir" "$preview"

shopt -s nullglob
if [ "${#wanted[@]}" -gt 0 ]; then
  pdfs=()
  for w in "${wanted[@]}"; do
    if [ -f "$w" ]; then
      pdfs+=("$w")
    elif [ -f "$src_dir/$(basename "$w")" ]; then
      pdfs+=("$src_dir/$(basename "$w")")
    else
      echo "error: '$w' not found in $src_dir/" >&2
      exit 1
    fi
  done
else
  pdfs=()
  for f in "$src_dir"/*.pdf; do
    base="$(basename "$f")"
    published="$pub_dir/$base"
    if [ "$force_all" = "1" ] || [ ! -f "$published" ] || [ "$f" -nt "$published" ]; then
      pdfs+=("$f")
    fi
  done
fi
shopt -u nullglob

if [ "${#pdfs[@]}" -eq 0 ]; then
  echo "Nothing to do: every deck in $src_dir/ is already published in $pub_dir/."
  echo "  (drop a new export into $src_dir/, or use --all to restage anyway)"
  exit 0
fi

# Published decks with no source in talks-original/ cannot be re-derived.
for f in "$pub_dir"/*.pdf; do
  [ -f "$src_dir/$(basename "$f")" ] || \
    echo "note: $f has no source in $src_dir/ (cannot be re-compressed from original)"
done

echo "Decks to process:"
printf '  %s\n' "${pdfs[@]#$src_dir/}"
echo

pairs=()
lint_findings=0
for pdf in "${pdfs[@]}"; do
  base="$(basename "$pdf" .pdf)"
  comp="$preview/${base}-compressed-${dpi}dpi.pdf"

  # ---- 1. QA before touching the file -----------------------------------
  echo "==> QA: $base"
  report="$preview/${base}-lint.txt"
  json="$preview/${base}-lint.json"
  "$lint" "$pdf" --json "$json" | tee "$report"
  n=$(python3 -c "import json,sys; d=json.load(open('$json')); print(sum(1 for f in d['findings'] if f['severity'] in ('high','medium','low')))" 2>/dev/null || echo 0)
  lint_findings=$((lint_findings + ${n:-0}))

  # ---- 2. compress -------------------------------------------------------
  echo "==> compress: $base"
  "$compress" "$pdf" "$comp" "$dpi" "$quality"
  pairs+=("$pdf" "$comp")
  echo
done

"$compare" "$preview/compare.html" "${pairs[@]}"

: >"$preview/.stage-manifest"
for ((i = 0; i < ${#pairs[@]}; i += 2)); do
  printf '%s\t%s\t%s\n' "$(shasum -a 256 "${pairs[$i]}" | cut -d' ' -f1)" \
    "${pairs[$i]}" "${pairs[$((i + 1))]}" >>"$preview/.stage-manifest"
done

echo
if [ "$lint_findings" -gt 0 ]; then
  echo "QA flagged $lint_findings item(s) - read preview/*-lint.txt and decide what"
  echo "to fix in the source deck BEFORE publishing. Fixing means re-exporting to"
  echo "$src_dir/ and re-running this script."
  echo
fi
echo "NEXT: review preview/compare.html"
echo "  - compare each slide side by side; zoom 200-400% to judge sharpness"
echo "  - check preview/*-lint.txt for typos/consistency issues"
echo "  - if both look good: .agents/skills/pdf-slide-compression/scripts/approve.sh"
echo
echo "Nothing was committed. $pub_dir/ is untouched."
command -v open >/dev/null 2>&1 && open "$preview/compare.html" || true
