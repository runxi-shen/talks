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
    MIT-ChemBio-2026-youtube.jpg
  SBI2-2026.pdf
  IUSM-CCBB-CarpenterShen-2026.pdf
  MIT_Chem_Biology_Guest_Lecture-2026.pdf
preview/                                # Review candidates and QA (gitignored)
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
   Compression only changes raster images; text, fonts and links are preserved.
   Size savings vary by deck. `docs/` only receives reviewed compressed files.
3. Save a first-slide preview or YouTube thumbnail in `docs/assets/`. Use the
   image's actual width and height in the page.
4. Copy a `<article class="talk">` block in `docs/index.html` and update its title,
   event, speakers, date, PDF links, preview, file size, and slide count. Give the
   title a unique `id` and match `aria-labelledby`. Use relative filenames in
   links, without a `docs/` prefix. Keep newest talks first, grouped by year.
5. Commit and push the approved PDF, thumbnail, and updated page. Do not add
   `preview/` or `talks-original/`, even with `git add -f`. Wait for deployment
   and verify the view, download, and video links.

Recorded talks go in the **Featured talks** section, above the chronological
collection, in the desired pinned order. Link the thumbnail and watch button to
YouTube, and the PDF buttons to the local file in `docs/`. Do not duplicate the
same talk in the collection. Videos are linked rather than embedded, so the page
loads without a YouTube player.

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
The local pre-commit hook rejects PDFs over 6 MiB or without a matching review
approval. Changed sources/previews must be restaged and reviewed again. A larger
reviewed deck can use an explicit `MAX_PDF_BYTES` limit; don't sacrifice clarity
just to meet the default cap.

Enable the hook once per clone:

```sh
git config core.hooksPath .githooks
```

Compression requires Python 3 with **pikepdf + Pillow** and **Poppler**
(`pdfinfo`, `pdftotext`, `pdftoppm`). If the Python packages aren't installed,
`pdf.sh` can obtain them through Nix. Automated spelling checks need Hunspell and
its `en_US` dictionary; otherwise the report explicitly marks spelling unavailable.
Do not treat that as a spelling pass.

Always compress from the original export, never an already-compressed PDF.
**Back up `talks-original/` separately:** gitignored files don't travel with a clone.
The scripts never commit or push automatically, and automated checks do not
replace visual review. Full workflow: `.agents/skills/pdf-slide-compression/SKILL.md`.

### Maintenance checks

Using a Python environment with pikepdf and Pillow:

```sh
python3 .agents/skills/pdf-slide-compression/scripts/test-pdf.py -v
```

The tests generate PDFs in a disposable repository, including the invisible-citation
regression, failed rendering, transparency preservation and stale-review rejection.
Published slides are not modified.

## Local preview

From the repository folder:

```sh
python3 -m http.server 8000 --directory docs
```

Open http://localhost:8000/. Stop the preview with Ctrl+C.
