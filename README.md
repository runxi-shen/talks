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

1. Export the final slides to PDF. Aim for under 25 MiB for easy browser uploads.
2. Save it in `docs/`. Use a short, stable filename with the year. Avoid spaces;
   capitalization matters. Do not rename an already-shared PDF.
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

## Local preview

From the repository folder:

```sh
python3 -m http.server 8000 --directory docs
```

Open http://localhost:8000/. Stop the preview with Ctrl+C.
