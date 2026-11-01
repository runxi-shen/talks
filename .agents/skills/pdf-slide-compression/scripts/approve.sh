#!/usr/bin/env bash
# Human approval gate. Run this AFTER eyeballing preview/compare.html.
#
# It asks you to confirm in the terminal (the agent cannot answer for you),
# then swaps the reviewed compressed PDFs into docs/, archives the full-res
# originals outside the repo, and records an approval token so the pre-commit
# hook will accept the commit.
#
# Usage: approve.sh [pdf ...]          # default: every staged pair
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
dpi="${DPI:-150}"
preview="preview"
manifest="$preview/.stage-manifest"
masters="${MASTERS_DIR:-$HOME/Documents/talks-masters-original}"
token="$repo_root/.git/pdf-review-approved"

[ -f "$manifest" ] || {
  echo "error: nothing staged. Run stage-for-review.sh first." >&2
  exit 1
}

pairs=()
while IFS=$'\t' read -r _ orig comp; do
  [ -f "$orig" ] && [ -f "$comp" ] && pairs+=("$orig" "$comp")
done <"$manifest"

if [ "${#pairs[@]}" -eq 0 ]; then
  echo "error: staged files are missing; re-run stage-for-review.sh" >&2
  exit 1
fi

if [ "$#" -gt 0 ]; then
  wanted=("$@")
  filtered=()
  for ((i = 0; i < ${#pairs[@]}; i += 2)); do
    for w in "${wanted[@]}"; do
      if [ "$(basename "${pairs[$i]}")" = "$(basename "$w")" ] || [ "${pairs[$i]}" = "$w" ]; then
        filtered+=("${pairs[$i]}" "${pairs[$((i + 1))]}")
      fi
    done
  done
  pairs=("${filtered[@]}")
fi

echo "Pending approval:"
for ((i = 0; i < ${#pairs[@]}; i += 2)); do
  orig="${pairs[$i]}"
  comp="${pairs[$((i + 1))]}"
  printf '  %-42s %6.2f MB -> %6.2f MB\n' "$orig" \
    "$(echo "$(wc -c <"$orig")/1048576" | bc -l)" \
    "$(echo "$(wc -c <"$comp")/1048576" | bc -l)"
done
echo
echo "Have you actually looked at $preview/compare.html and confirmed the"
echo "compressed slides are sharp enough? Reviewing is the whole point of this gate."
echo

if [ ! -t 0 ]; then
  echo "error: approval requires an interactive terminal." >&2
  echo "Run this yourself in your shell: $0" >&2
  exit 1
fi

printf 'Type "approved" to swap in the compressed files: '
read -r answer
if [ "$answer" != "approved" ]; then
  echo "aborted; docs/ untouched."
  exit 1
fi

mkdir -p "$masters"
: >>"$token"
for ((i = 0; i < ${#pairs[@]}; i += 2)); do
  orig="${pairs[$i]}"
  comp="${pairs[$((i + 1))]}"
  cp -p "$orig" "$masters/$(basename "$orig")"
  cp "$comp" "$orig"
  sum="$(shasum -a 256 "$orig" | cut -d' ' -f1)"
  grep -v " $(printf '%s' "$orig")\$" "$token" >"$token.tmp" 2>/dev/null || true
  mv "$token.tmp" "$token"
  printf '%s %s\n' "$sum" "$orig" >>"$token"
  printf 'approved+swapped %-42s %6.2f MB\n' "$orig" \
    "$(echo "$(wc -c <"$orig")/1048576" | bc -l)"
done

echo
echo "Full-res originals archived in: $masters"
echo "Now commit, e.g.:"
echo "  git add docs/ && git commit -m 'docs(slides): update <deck>' && git push"
