---
name: pdf-slide-compression
description: QA, compress and review new or corrected slide PDFs in this talks repo. Use when an export arrives in talks-original/, a deck needs publishing, or the PDF review hook blocks a commit. Never publish a PDF without the user's visual inspection and approval.
---

# Slide PDFs: QA → compress → review → publish

## Files

- `talks-original/`: full-resolution exports, **gitignored**; never overwrite them.
- `preview/`: compressed candidates, QA reports and comparison page, **gitignored**.
- `docs/`: published PDFs. Keep existing public filenames stable.

Only three production scripts: `scripts/pdf.sh` orchestrates the workflow,
`scripts/compress-images.py` compresses and verifies, and `scripts/lint-slides.py`
provides QA pointers. `scripts/test-pdf.py` is the regression suite.

## Workflow

Run from the repository root (resolve these commands relative to this skill's
`scripts/` directory if working elsewhere):

```sh
.agents/skills/pdf-slide-compression/scripts/pdf.sh stage
# One deck: append SBI2-2026.pdf. All decks: append --all.
# Higher image resolution: prefix with DPI=192.
```

This detects new/newer exports in `talks-original/`, lints them **before**
compression, verifies the result and opens `preview/compare.html`.
`docs/` remains untouched. Detection uses modification times: when unsure, give an
explicit filename or `--all`; do not touch timestamps to hide pending work.

1. Read `preview/*-lint.txt`. Report likely typos, term/style inconsistencies,
   citation pointers and layout warnings **with slide numbers**. Fix real issues
   in the editable deck, re-export to `talks-original/`, and restage.
2. Ask the user to inspect the original/compressed comparison, especially citations,
   fine figure labels, transparency and photo detail. Wait for their approval.
3. The **user** runs the interactive gate:

   ```sh
   .agents/skills/pdf-slide-compression/scripts/pdf.sh approve
   # Append a filename to approve only that deck.
   ```

   It checks that both source and preview still match the reviewed hashes, copies
   into `docs/`, and records local approval. Changed files require restaging.
4. Update `docs/index.html` sizes and page counts from the actual approved PDFs.
   Update `docs/assets/` only if the title slide changed.
5. Commit only the approved PDFs and associated website edits; push and check the
   live site. Do not rewrite history or change unrelated decks.

**Never manufacture approval tokens, simulate the user's terminal, bypass the hook,
copy candidates into docs/ yourself, or treat automated checks as visual approval.**
The local hook must be enabled per clone: `git config core.hooksPath .githooks`.
It rejects staged PDFs without matching approval (including renames), and PDFs over
6 MiB. A reviewed deck may legitimately need a higher `MAX_PDF_BYTES`; do not
reduce quality merely to satisfy a size cap.

## Compression safeguards

- Use pikepdf + Pillow for **images only**. Do not reintroduce Ghostscript: its font
  rewriting previously broke Unicode extraction and made citations invisible.
- Default target: 150 DPI at each image's largest measured placement, JPEG quality
  85. Unmeasured images, alpha masks and unsupported colour/encoding cases stay
  untouched. Always compress the original export, never a published/compressed PDF.
- Before replacing an output: require successful Poppler tools, matching page
  counts, exact extracted text, matching render dimensions and a per-word ink
  comparison against the source. Failures abort without replacing existing output.
- Text-visibility checks are **heuristics**. They do not certify figures, colours,
  scientific claims, citation accuracy, grammar or text baked into images. The QA
  report is advisory too; it explicitly reports unavailable spell checking.

## Dependencies and tests

Python 3 with `pikepdf` and `Pillow`, plus Poppler (`pdfinfo`, `pdftotext`,
`pdftoppm`). `pdf.sh` uses installed Python packages or a cached Nix environment.
Hunspell + its `en_US` dictionary enables automated spell checking; without it,
the report says the check is unavailable, not that spelling passed. Agents must
still proofread the extracted slide text and report likely errors before asking
for visual approval. Help, no-op staging and approval never fetch dependencies.

```sh
# Use the Python environment containing pikepdf and Pillow:
python3 .agents/skills/pdf-slide-compression/scripts/test-pdf.py -v
```

Tests generate their own PDFs and disposable repository; never stage test exports
in the real repo. Do not delete reflogs or prune history as routine cleanup.

`talks-original/` is ignored, not backed up by Git. Keep an independent backup.
