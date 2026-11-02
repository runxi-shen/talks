#!/usr/bin/env bash
# Human approval gate. Run this AFTER reviewing preview/compare.html and
# preview/*-lint.txt.
#
# It asks you to confirm in the terminal (an agent cannot answer for you), then
# copies the reviewed compressed PDFs into docs/ and records an approval token
# so the pre-commit hook will accept the commit. talks-original/ is never
# modified - it stays the untouched source of truth.
#
# Usage: approve.sh [deck ...]      # default: everything currently staged
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

dpi="${DPI:-150}"
pub_dir="docs"
preview="preview"
manifest="$preview/.stage-manifest"
token="$repo_root/.git/pdf-review-approved"

[ -f "$manifest" ] || {
  echo "error: nothing staged. Run stage-for-review.sh first." >&2
  exit 1
}

pairs=()
while IFS=$'\t' read -r _ src comp; do
  [ -f "$src" ] && [ -f "$comp" ] && pairs+=("$src" "$comp")
done <"$manifest"

if [ "${#pairs[@]}" -eq 0 ]; then
  echo "error: staged files are missing; re-run stage-for-review.sh" >&2
  exit 1
fi

if [ "$#" -gt 0 ]; then
  filtered=()
  for ((i = 0; i < ${#pairs[@]}; i += 2)); do
    for w in "$@"; do
      if [ "$(basename "${pairs[$i]}")" = "$(basename "$w")" ]; then
        filtered+=("${pairs[$i]}" "${pairs[$((i + 1))]}")
      fi
    done
  done
  if [ "${#filtered[@]}" -eq 0 ]; then
    echo "error: none of the given decks are currently staged" >&2
    exit 1
  fi
  pairs=("${filtered[@]}")
fi

echo "Pending approval:"
for ((i = 0; i < ${#pairs[@]}; i += 2)); do
  src="${pairs[$i]}"
  comp="${pairs[$i + 1]}"
  printf '  %-44s %6.2f MB -> %6.2f MB\n' "$(basename "$src")" \
    "$(echo "$(wc -c <"$src")/1048576" | bc -l)" \
    "$(echo "$(wc -c <"$comp")/1048576" | bc -l)"
done
echo

lint_reports=()
for ((i = 0; i < ${#pairs[@]}; i += 2)); do
  base="$(basename "${pairs[$i]}" .pdf)"
  [ -f "$preview/${base}-lint.txt" ] && lint_reports+=("$preview/${base}-lint.txt")
done
if [ "${#lint_reports[@]}" -gt 0 ]; then
  echo "QA reports (${#lint_reports[@]}):"
  printf '  %s\n' "${lint_reports[@]}"
  if grep -qE '^\s+(high|medium)\s' "${lint_reports[@]}" 2>/dev/null; then
    echo
    echo "  ⚠ some high/medium findings remain. Confirm they are acceptable"
    echo "    (or fix the source deck and re-run stage-for-review.sh)."
  fi
  echo
fi

echo "Have you looked at preview/compare.html and the QA reports, and confirmed"
echo "the slides are correct and sharp enough?"
echo

if [ ! -t 0 ]; then
  echo "error: approval requires an interactive terminal." >&2
  echo "Run this yourself in your shell: $0" >&2
  exit 1
fi

printf 'Type "approved" to publish the compressed files: '
read -r answer
if [ "$answer" != "approved" ]; then
  echo "aborted; $pub_dir/ untouched."
  exit 1
fi

: >>"$token"
for ((i = 0; i < ${#pairs[@]}; i += 2)); do
  comp="${pairs[$i + 1]}"
  base="$(basename "${pairs[$i]}")"
  dest="$pub_dir/$base"
  cp "$comp" "$dest"
  sum="$(shasum -a 256 "$dest" | cut -d' ' -f1)"
  grep -v " $(printf '%s' "$dest")\$" "$token" >"$token.tmp" 2>/dev/null || true
  mv "$token.tmp" "$token"
  printf '%s %s\n' "$sum" "$dest" >>"$token"
  printf 'approved %-44s %6.2f MB\n' "$dest" "$(echo "$(wc -c <"$dest")/1048576" | bc -l)"
done

echo
echo "Sources left untouched in talks-original/."
echo "Now commit, e.g.:"
echo "  git add $pub_dir/ && git commit -m 'docs(slides): publish <deck>' && git push"
