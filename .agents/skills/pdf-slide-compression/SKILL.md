---
name: pdf-slide-compression
description: Shrink slide-deck PDFs exported from PowerPoint/Keynote before committing them to this repo, and enforce human review of the result. Use whenever a new or updated PDF lands in docs/ (new talk, revised slides, "update the deck", "corrections"), or when the repo/pre-commit hook complains about an oversized PDF.
---

# Slide PDF compression + review gate

Deck PDFs straight from PowerPoint/Keynote are ~10 MB because images are embedded at
4K (3840x2160) or higher for a 10-inch-wide slide. Downsampling images to 150 dpi takes
them to ~2.5-3 MB (-70%) with vector text, fonts, and links fully intact. That is the
whole trick; nothing else is needed.

## Hard rule: never commit a PDF a human has not looked at

Compression is lossy on photos. The agent must **never** commit, `git add`-and-commit, or
push a slide PDF until the human has seen the side-by-side comparison and explicitly
approved it. Do not "assume it's fine", do not skip the gate because the change was small,
and do not run `approve.sh` on the human's behalf - it is interactive on purpose and will
refuse a non-tty stdin.

The `.githooks/pre-commit` hook enforces this mechanically: staged PDFs over 4 MiB, or
without an approval token in `.git/pdf-review-approved`, are rejected.

## Workflow

When a new export arrives (say `docs/SBI2-2026.pdf` was overwritten with a fresh export):

1. Stage a compressed copy for review. This does **not** touch `docs/` and does **not**
   commit anything:

   ```bash
   .agents/skills/pdf-slide-compression/scripts/stage-for-review.sh
   # or a single deck:
   .agents/skills/pdf-slide-compression/scripts/stage-for-review.sh docs/SBI2-2026.pdf
   # higher quality if projecting on 1080p+:
   DPI=192 .agents/skills/pdf-slide-compression/scripts/stage-for-review.sh
   ```

2. **Stop and hand it to the human.** Tell them to open `preview/compare.html`, flip
   through the photo-heavy slides, and zoom to 200-400%. Report the size numbers from the
   script output. Wait for an explicit yes.

3. Only after approval, the human runs the gate themselves:

   ```bash
   .agents/skills/pdf-slide-compression/scripts/approve.sh
   ```

   It prompts for `approved`, swaps the compressed files into `docs/`, archives the
   full-res originals to `~/Documents/talks-masters-original/`, and records the approval
   token.

4. Then commit and push:

   ```bash
   git add docs/ && git commit -m "docs(slides): update <deck>" && git push
   ```

## Sizing guide

Slide is 10 in wide, so `dpi x 10` = rendered pixel width.

| dpi | size (typical 29-slide deck) | use when |
|-----|------------------------------|----------|
| 150 | ~2.8 MB (-70%) | default; fine for on-screen reading |
| 192 | ~3.6 MB (-60%) | projecting on 1080p, want zero softening |

Below 150 dpi you stop saving much and start losing legibility on fine figures.

## Rules of thumb

- **Never compress an already-compressed PDF.** The script re-encodes JPEGs, so chaining
  passes accumulates generation loss. Always compress from the original PPT/Keynote PDF
  export. Originals are archived in `~/Documents/talks-masters-original/`.
- **Never convert these decks to HTML.** Rasterised slides are *bigger* than the
  compressed PDF and destroy selectable text; PDF-to-HTML conversion of designed decks
  reflows badly. Serve the PDF; browsers render it natively.
- Verify after compressing: same page count, same word count (`pdftotext`), 66 font
  subsets preserved, link annotations preserved. `compress-pdf.sh` checks and warns.
- The Og image/thumbnail in `docs/assets/` only needs regenerating if the *title* slide
  changed - compare page 1 text first.

## Files

- `scripts/compress-pdf.sh` - one file: `<in> <out> [dpi] [quality]`
- `scripts/stage-for-review.sh` - compress into `preview/`, build `preview/compare.html`
- `scripts/approve.sh` - interactive approval, swap into `docs/`, archive originals
- `scripts/make-comparison.py` - builds the side-by-side review page
- `.githooks/pre-commit` - blocks oversized or unreviewed PDFs
