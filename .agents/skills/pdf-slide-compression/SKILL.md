---
name: pdf-slide-compression
description: Shrink slide-deck PDFs exported from PowerPoint/Keynote before committing them to this repo, QA them for typos and layout problems, and enforce human review of the result. Use whenever a new or updated deck lands in talks-original/ or docs/ (new talk, revised slides, "update the deck", "corrections"), or when the pre-commit hook complains about an oversized PDF.
---

# Slide deck pipeline: QA → compress → human review → publish

Deck PDFs straight from PowerPoint/Keynote are ~10 MB because images are embedded at
4K+ for a 10-inch-wide slide. Downsampling to 150 dpi takes them to ~2.5-3 MB (-70%)
with vector text, fonts, and links intact.

## Layout

```
talks-original/     full-res exports, GITIGNORED - the source of truth
docs/               published, compressed PDFs only (this is the website)
preview/            review scratch, GITIGNORED
```

Never edit `docs/*.pdf` by hand and never compress an already-compressed file
(repeated JPEG passes accumulate loss). `docs/` is generated output: it only ever
receives files that came through `talks-original/`.

## Hard rule: never commit a PDF a human has not looked at

Compression is lossy on photos, and the QA pass cannot judge scientific accuracy.
Before any `git add`/commit/push of a deck, the human must have:

1. seen the side-by-side comparison, and
2. read the QA report.

Do **not** decide on the human's behalf, do not skip the gate for a "small" change,
and never run `approve.sh` yourself - it is interactive and refuses a non-tty stdin.

`.githooks/pre-commit` enforces this: staged PDFs over 4 MiB, or without an approval
token in `.git/pdf-review-approved`, are rejected.

## Workflow

1. Export slides to PDF and drop the file into `talks-original/`.

2. Stage it for review. This runs QA, compresses, and builds the comparison page.
   It does **not** touch `docs/` and does **not** commit:

   ```bash
   .agents/skills/pdf-slide-compression/scripts/stage-for-review.sh
   ```

   With no arguments it processes only decks that are new or newer than their
   published copy. Options: `NAME.pdf` for one deck, `--all` to restage everything,
   `DPI=192` for higher quality.

3. **Read `preview/*-lint.txt`** and fix real problems **in the source deck**, then
   re-export and re-run step 2. Do not "fix" typos by editing the PDF.

4. **Hand the comparison to the human** (`preview/compare.html`, open automatically).
   Report the size numbers and the QA summary. Wait for an explicit yes.

5. The human runs the gate themselves:

   ```bash
   .agents/skills/pdf-slide-compression/scripts/approve.sh
   ```

   It prompts for `approved`, copies the compressed files into `docs/`, and records
   an approval token. `talks-original/` is never modified.

6. Commit and push:

   ```bash
   git add docs/ && git commit -m "docs(slides): publish <deck>" && git push
   ```

## The QA pass (`lint-slides.py`)

Runs before compression and reports pointers, not verdicts.

| Check | What it catches |
|-------|-----------------|
| spelling | unknown words, via hunspell (nix) or `/usr/share/dict/words` |
| typos | doubled words (`from from`), double spaces, space before punctuation, missing space after comma/colon, repeated punctuation |
| consistency | same term spelled differently across slides (`Cell Painting` / `Cell-Painting`, `in vivo` / `in-vivo`, `Single-cell` / `single-cell`), mixed straight/curly quotes, number formats |
| citations | `et al.` with no year, mixed `Figure` / `Fig.` / `Table` / `Tab.` styles, gaps in numbered refs |
| layout | text outside the page box, overlapping text runs, font-size outliers, dense slides |

**It cannot**: verify a claim is scientifically correct, read text baked into images
(most of a figure), confirm a citation exists, or judge whether a sentence reads
well. Grammar is only checked mechanically. Sparse findings do not mean the deck is
correct - the human review in step 4 is still mandatory.

Add domain vocabulary to stop false spelling hits, either in `BUILTIN_ALLOW` in
`lint-slides.py` or per deck with `--words extra-terms.txt`.

## Sizing guide

Slide is 10 in wide, so `dpi x 10` = rendered pixel width.

| dpi | size (typical 29-slide deck) | use when |
|-----|------------------------------|----------|
| 150 | ~2.8 MB (-70%) | default; fine for on-screen reading |
| 192 | ~3.6 MB (-60%) | projecting on 1080p, want zero softening |

Below 150 dpi you stop saving much and start losing legibility on fine figures.

## Pitfalls

- **Never use ghostscript's `-dFastWebView`.** It writes a corrupt linearization
  hint table (`qpdf --check`: `read_bits: too many bits requested`, and `pdfinfo`
  warns on every read). The script linearizes with `qpdf --linearize` afterwards and
  runs `qpdf --check` as a regression guard.
- **Never convert these decks to HTML.** Rasterised slides are bigger than the
  compressed PDF and destroy selectable text; PDF-to-HTML of designed decks reflows
  badly. Serve the PDF.
- **Don't rely on `git status` to spot repo bloat.** `git add` writes blobs even if
  you never commit, and reflogs keep old history alive. After a rewrite or a staging
  test, check `du -sh .git` and `git count-objects -vH`, then
  `git reflog expire --expire=now --all && git gc --prune=now`.
- The preview thumbnail in `docs/assets/` only needs regenerating if the **title**
  slide changed - compare page 1 text first.
- Verify after compressing: same page count, same word count, fonts and link
  annotations preserved. `compress-pdf.sh` checks and warns.

## Files

- `scripts/lint-slides.py` - QA pass (`--json`, `--words`, `--strict`)
- `scripts/compress-pdf.sh` - `<in> <out> [dpi] [quality]`
- `scripts/stage-for-review.sh` - detect unconverted decks, QA, compress, compare page
- `scripts/approve.sh` - interactive approval, copies into `docs/`
- `scripts/make-comparison.py` - builds the side-by-side review page
- `.githooks/pre-commit` - blocks oversized or unreviewed PDFs
