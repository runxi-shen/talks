# Talks

Public talks and downloadable slides by Runxi Shen.

Website: https://runxi-shen.github.io/talks/

## Structure

```text
README.md
LICENSE
.gitignore
docs/                              # Published website (URL root)
  index.html                       # Talk listings, newest first
  style.css                        # Homepage-inspired light/dark styles
  script.js                        # Theme toggle
  .nojekyll                        # Serve static files directly
  assets/                          # Slide preview images
    SBI2-2026.png
    IUSM-CCBB-2026.png
  SBI2-2026.pdf
  IUSM-CCBB-CarpenterShen-2026.pdf
talks-original/                         # Full-res exports (gitignored)
.agents/skills/pdf-slide-compression/   # Skill: QA + compress + review gate
.githooks/pre-commit                    # Blocks oversized/unreviewed PDFs
```

GitHub Pages publishes the **contents** of `docs/`, not the folder name.
For example, `docs/SBI2-2026.pdf` is served at:

https://runxi-shen.github.io/talks/SBI2-2026.pdf

This keeps the repository root tidy without redirects, duplicate PDFs, a build
script, or a custom deployment workflow. Keep PDFs directly in `docs/` to preserve
short addresses. Only put material intended for public distribution in this repo;
keep editable decks and drafts elsewhere.

## GitHub Pages setup

After committing and pushing this layout, open **Settings → Pages** and select:

- Source: **Deploy from a branch**
- Branch: **main**
- Folder: **/docs** (not **/ (root)**)

Save, wait for the Pages deployment, and verify the website and PDF links.
The source-folder change is required for this layout. Existing PDF URLs stay the
same once the new source is deployed. No dependencies or build commands are needed.

## Add a talk

1. Export the final slides to PDF and save it in `talks-original/` (gitignored).
   Use a short, stable filename with the year. Avoid spaces; capitalization
   matters. Do not rename an already-shared PDF.
2. Run the QA + compression pipeline and review it before committing — see below.
   A raw PowerPoint export is ~10 MB; 150 dpi brings it to ~2.8 MB with text and
   links intact. `docs/` only ever receives compressed files.
3. Save a first-slide preview in `docs/assets/`. Use the image's actual width and
   height in the page; the current previews are 1200 × 675 pixels.
4. Copy a `<article class="talk">` block in `docs/index.html` and update its title,
   event, speakers, date, PDF links, preview, file size, and slide count. Give the
   title a unique `id` and match `aria-labelledby`. Use relative filenames in
   links, without a `docs/` prefix. Keep newest talks first, grouped by year.
5. Commit and push the PDF, preview, and updated page. Wait for deployment and
   verify the view and download links.

Share the HTTPS PDF address in email and QR codes. To correct slides, replace the
same file; for a distinct talk, use a new filename. Downloads work without JavaScript.

## QA, compress and review decks

PowerPoint/Keynote embeds images at 4K for a 10-inch-wide slide, which is why raw
exports hit ~10 MB. Images are downsampled; vector text, fonts, and links are kept.

```sh
# 1. QA + compress everything new/unconverted, then open a comparison page
.agents/skills/pdf-slide-compression/scripts/pdf.sh stage

# 2. read the QA reports and the comparison yourself
cat preview/*-lint.txt        # typos, term inconsistency, layout problems
#    preview/compare.html opens automatically; zoom 200-400%

# 3. fix real issues in the source deck, re-export, re-run step 1

# 4. if it all looks good, approve (interactive prompt; copies into docs/)
.agents/skills/pdf-slide-compression/scripts/pdf.sh approve
```

`talks-original/` is your source of truth and is never modified by the pipeline.
A pre-commit hook rejects any staged PDF over 4 MiB, or one that was never approved,
so decks cannot reach the site without a human looking at them.

Enable the hook once per clone:

```sh
git config core.hooksPath .githooks
```

Always compress from the original export in `talks-original/`, never from an
already-compressed PDF (repeated JPEG passes accumulate loss). Emergency override:
`ALLOW_UNREVIEWED_PDF=1 git commit ...`. Full details live in
`.agents/skills/pdf-slide-compression/SKILL.md`.

## Local preview

From the repository folder:

```sh
python3 -m http.server 8000 --directory docs
```

Open http://localhost:8000/. Stop the preview with Ctrl+C.
