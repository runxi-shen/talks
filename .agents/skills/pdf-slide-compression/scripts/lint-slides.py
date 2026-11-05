#!/usr/bin/env python3
"""Pre-compression slide QA: flag likely typos, layout problems, and
cross-slide inconsistency in a PDF exported from PowerPoint/Keynote.

Usage: lint-slides.py <deck.pdf> [--json out.json] [--words extra-terms.txt]

This is a LINTER, not a proofreader. It reports pointers for a human to judge.
It cannot verify whether a claim is scientifically correct, cannot read text
baked into images, and cannot check citations against reality.

Checks:
  spelling      unknown words (requires installed hunspell + en_US dictionary)
  typos         doubled words, double spaces, space-before-punctuation,
                missing space after punctuation, repeated punctuation
  consistency   terms that vary in hyphenation/spacing/capitalisation,
                straight vs curly quotes mixed within one deck,
                number-format variants (1,000 vs 1000)
  citations     "et al." without a nearby year, inconsistent figure/table
                abbreviations, gaps in bracketed reference numbers
  layout        text outside the page box, possible text overlaps,
                small-text outliers and dense slides

Exit code: 0 always unless --strict, so this never silently blocks a review.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

# --- technical terms a generic dictionary will not know ---------------------
BUILTIN_ALLOW = {
    "rnaseq", "rna", "rnas", "dna", "mrna", "cdna", "scrna", "crispr", "grna",
    "morpholino", "proteomics", "transcriptomics", "genomics", "microscopy",
    "bioimage", "bioimaging", "phenomics", "highcontent", "morphological",
    "embeddings", "embedding", "autoencoder", "autoregressive", "selfsupervised",
    "unsupervised", "segmentation", "phenotype", "phenotypes", "phenotypic",
    "multiplexed", "multimodal", "spatiotemporal", "organoid", "organoids",
    "fluorescence", "immunofluorescence", "cryo", "confocal", "facs",
    "perturbation", "perturbational", "hitpicking", "sbi", "sbi2", "iusm",
    "ccbb", "purdue", "numpy", "pytorch", "tensorflow", "jupyter", "python",
    "github", "doi", "preprint", "biomol", "els", "singh", "shen", "carpenter",
    "munoz", "alán", "runxi", "carpenter-shen", "imagej", "cellprofiler",
    "cellpose", "phenograph", "umap", "tsne", "pca", "vi", "vae", "gan",
    "gans", "cnn", "cnns", "resnet", "batchnorm", "dropout", "hyperparameter",
    "hyperparameters", "latent", "zscore", "zscored", "pvalue", "pvalues",
    "fdr", "auc", "roc", "mse", "top1", "topk", "npj", "biorxiv", "arxiv",
    "citeseer", "et", "al", "vs", "e", "g", "ie", "eg", "cf", "sb", "cvd",
}


def poppler():
    for tool in ("pdftotext", "pdfinfo"):
        if not shutil.which(tool):
            sys.exit(f"error: {tool} not found (install poppler)")


def pages_of(pdf):
    out = subprocess.run(["pdfinfo", pdf], capture_output=True, text=True, check=True).stdout
    m = re.search(r"^Pages:\s+(\d+)", out, re.M)
    if not m or int(m.group(1)) < 1:
        raise ValueError(f"Cannot determine page count: {pdf}")
    return int(m.group(1))


def text_of(pdf, page):
    # -layout padding creates bogus double-space/doubled-word findings.
    return subprocess.run(["pdftotext", "-f", str(page), "-l", str(page), pdf, "-"],
                          capture_output=True, text=True, check=True).stdout


def bbox_of(pdf, page):
    """Parse pdftotext -bbox into a list of (page, word, xmin, ymin, xmax, ymax)."""
    r = subprocess.run(
        ["pdftotext", "-f", str(page), "-l", str(page), "-bbox", pdf, "-"],
        capture_output=True, text=True, check=True,
    )
    words = []
    root = ET.fromstring(r.stdout)
    ns = {"x": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}
    pre = "{%s}" % ns["x"] if ns else ""
    pw = ph = 0.0
    for pg in root.iter(f"{pre}page"):
        pw = float(pg.get("width", 0))
        ph = float(pg.get("height", 0))
        for w in pg.iter(f"{pre}word"):
            words.append(
                (
                    w.text or "",
                    float(w.get("xMin", 0)),
                    float(w.get("yMin", 0)),
                    float(w.get("xMax", 0)),
                    float(w.get("yMax", 0)),
                )
            )
    return words, (pw, ph)


# --- spell checking --------------------------------------------------------
def spell_checker():
    """Use an installed dictionary; never silently claim a failed checker passed."""
    exe = shutil.which("hunspell")
    if exe:
        probe = subprocess.run([exe, "-l", "-d", "en_US"], input="hello\n",
                               capture_output=True, text=True)
        if probe.returncode != 0:
            exe = None
    if exe:
        def check(words):
            proc = subprocess.run(
                [exe, "-l", "-d", "en_US"], input="\n".join(words),
                capture_output=True, text=True,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"hunspell failed: {proc.stderr.strip()}")
            return {w.strip() for w in proc.stdout.splitlines() if w.strip()}
        return check, "hunspell"

    return None, "unavailable"


WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’\-]*[A-Za-z]|[A-Za-z]")


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("pdf")
    ap.add_argument("--json")
    ap.add_argument("--words", help="file with extra allowed words, one per line")
    ap.add_argument("--strict", action="store_true", help="exit 1 if any issue found")
    args = ap.parse_args()

    poppler()
    pdf = args.pdf
    if not os.path.exists(pdf):
        sys.exit(f"error: no such file: {pdf}")

    n_pages = pages_of(pdf)
    allow = set(BUILTIN_ALLOW)
    if args.words:
        with open(args.words, encoding="utf-8") as fh:
            allow |= {w.strip().lower() for w in fh if w.strip()}

    pages = {}
    per_page_words = {}
    findings = []

    def add(kind, page, detail, severity="note"):
        findings.append({"kind": kind, "page": page, "detail": detail, "severity": severity})

    for p in range(1, n_pages + 1):
        t = text_of(pdf, p)
        pages[p] = t
        per_page_words[p] = WORD_RE.findall(t)

    # ---- typos / mechanical ----
    for p in range(1, n_pages + 1):
        t = pages[p]
        # doubled words: alphabetic, 2+ chars, same line (no newline between)
        for m in re.finditer(r"\b([A-Za-z][A-Za-z'’]{1,})[ \t]+\1\b", t, re.I):
            if m.group(1).lower() not in {"that", "had", "is"}:
                add("typos", p, f"doubled word: '{m.group(0).strip()}'", "high")
        if re.search(r"\S[ \t]{2,}\S", t):
            add("typos", p, "double space", "low")
        for m in re.finditer(r"[ \t]+[,;:.!?]", t):
            add("typos", p, f"space before punctuation: '{m.group(0)!r}'", "medium")
        for m in re.finditer(r"[a-z]{2,}[,;:][A-Za-z]", t):
            add("typos", p, f"missing space after punctuation: '{m.group(0)}'", "medium")
        for m in re.finditer(r"([!?.,;:])\1{1,}", t):
            add("typos", p, f"repeated punctuation: '{m.group(0)}'", "low")

    # ---- spelling ----
    checker, engine = spell_checker()
    unknown = {}
    if checker:
        # Keep casing so we can report it as it appears; skip all-caps and numbers.
        candidates = set()
        for p in range(1, n_pages + 1):
            for w in per_page_words[p]:
                wl = w.lower().strip("-'’")
                if len(wl) < 3 or wl in allow:
                    continue
                if w.isupper():                      # acronyms
                    continue
                if "-" in wl:                        # check each half separately
                    for part in wl.split("-"):
                        if len(part) >= 3 and part not in allow:
                            candidates.add(part)
                    continue
                candidates.add(wl)
        bad = checker(sorted(candidates))
        for p in range(1, n_pages + 1):
            for w in per_page_words[p]:
                for wl in w.lower().strip("-'’").split("-"):
                    if wl in bad and len(wl) >= 3:
                        unknown.setdefault(wl, []).append(p)
        for w, pgs in sorted(unknown.items()):
            add("spelling", sorted(set(pgs)), f"unknown word: '{w}'", "medium")
    else:
        add("spelling", "-", "Spell check unavailable: install hunspell + en_US dictionary", "info")

    # ---- consistency ----
    full = "\n".join(pages[p] for p in range(1, n_pages + 1))

    def variant_key(w):
        return re.sub(r"[\s\-]", "", w).lower()

    groups = {}
    for w in set(WORD_RE.findall(full)):
        if len(w) < 4:
            continue
        if "-" in w:
            groups.setdefault(variant_key(w), set()).add(w)
    # also catch "single cell" vs "single-cell"
    for m in re.finditer(r"\b(\w+)\s(\w+)\b", full):
        joined = m.group(1) + "-" + m.group(2)
        if joined in full:
            groups.setdefault(variant_key(joined), set()).update({joined, m.group(0)})
    for key, variants in sorted(groups.items()):
        if len(variants) > 1:
            add("consistency", "-", "term varies: " + " | ".join(sorted(variants)), "medium")

    straight = len(re.findall(r"(?<![A-Za-z])'|'(?![A-Za-z])", full)) + full.count('"')
    curly = full.count("’") + full.count("“") + full.count("”")
    if straight and curly:
        add("consistency", "-", f"mixed quote styles: {straight} straight vs {curly} curly", "low")

    for pat, label in (
        (r"\b\d{1,3},\d{3}\b", "thousands-separated (1,000)"),
        (r"\b\d{4,}\b", "plain digits (1000)"),
    ):
        hits = re.findall(pat, full)
        if hits:
            add("consistency", "-", f"number format present: {label} x{len(hits)}", "info")

    # ---- citations ----
    label_styles = {}
    etal_pages = []
    for p in range(1, n_pages + 1):
        t = pages[p]
        if re.search(r"et\s+al\b\.?(?![^.\n]{0,40}\d{4})", t, re.I):
            etal_pages.append(p)
        for m in re.finditer(r"\b(Figure|Fig\.|Table|Tab\.)\s*\d+", t):
            style = "Figure" if m.group(1).lower() == "figure" else "Fig."
            if m.group(1).lower() == "table":
                style = "Table"
            elif m.group(1).lower() == "tab.":
                style = "Tab."
            label_styles.setdefault(style, []).append(p)

    if etal_pages:
        add("citations", "-", f"'et al.' with no year on {len(etal_pages)} page(s): "
                             f"p{','.join(map(str, etal_pages))} (may be intentional short-form)",
            "low")

    for variants in (("Figure", "Fig."), ("Table", "Tab.")):
        if all(style in label_styles for style in variants):
            add("citations", "-", "label abbreviation varies: " + " / ".join(variants), "medium")

    ref_numbers = [int(x) for x in re.findall(r"\[(\d{1,3})\]", full)]
    if ref_numbers:
        mx = max(ref_numbers)
        missing = [i for i in range(1, mx + 1) if i not in set(ref_numbers)]
        if missing:
            add("citations", "-", f"bracketed ref numbers missing from sequence: {missing[:12]}", "medium")

    # ---- layout ----
    for p in range(1, n_pages + 1):
        words, (pw, ph) = bbox_of(pdf, p)
        if not words or not pw:
            add("layout", p, "no extractable text (image-only slide?)", "info")
            continue
        margin = 2.0
        outside = [w for w, x0, y0, x1, y1 in words if x0 < -margin or y0 < -margin
                   or x1 > pw + margin or y1 > ph + margin]
        if outside:
            add("layout", p, f"{len(outside)} word(s) outside the page box: "
                             f"{', '.join(outside[:4])}", "high")

        heights = [y1 - y0 for _, _, y0, _, y1 in words if y1 - y0 > 0]
        if heights:
            hs = sorted(heights)
            med = hs[len(hs) // 2]
            tiny = [w for w, _, y0, _, y1 in words if (y1 - y0) < med * 0.45]
            # small text is often intentional (source lines / credits): keep at low
            if len(tiny) > max(6, 0.08 * len(words)):
                add("layout", p, f"{len(tiny)} far-smaller-than-median text run(s): "
                                 f"{', '.join(tiny[:5])}", "low")

        # crude overlap: same visual line, horizontal ranges intersecting a lot
        rows = {}
        for w, x0, y0, x1, y1 in words:
            key = round(y0 / 3.0)
            rows.setdefault(key, []).append((x0, x1, w))
        overlaps = []
        for row in rows.values():
            row.sort()
            for (a0, a1, aw), (b0, b1, bw) in zip(row, row[1:]):
                if b0 < a1 - 2.0:
                    overlaps.append(f"'{aw}'/'{bw}'")
        if overlaps:
            add("layout", p, f"{len(overlaps)} overlapping text pair(s): "
                             f"{', '.join(overlaps[:4])} (labels on diagrams are often fine)",
                "low" if len(overlaps) > 1 else "medium")

        if len(words) > 160:
            add("layout", p, f"dense slide: {len(words)} words", "low")

    # ---- report ----
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    findings.sort(key=lambda f: (order.get(f["severity"], 9),
                                 f["page"] if isinstance(f["page"], int) else 0))

    counts = {}
    for f in findings:
        counts[f["kind"]] = counts.get(f["kind"], 0) + 1

    name = os.path.basename(pdf)
    print(f"\n=== slide QA: {name} ({n_pages} pages, speller: {engine}) ===")
    if not findings:
        print("  no issues detected by the automated checks.")
    else:
        cur = None
        for f in findings:
            if f["kind"] != cur:
                cur = f["kind"]
                print(f"\n  [{cur}]")
            pg = f["page"]
            if isinstance(pg, list):
                pg = "p" + ",".join(str(x) for x in pg)
            else:
                pg = f"p{pg}" if isinstance(pg, int) else "all"
            print(f"    {f['severity']:6} {pg:10} {f['detail']}")

    print("\n  summary: " + (", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
                             or "clean"))
    print("  NOTE: automated checks only. They cannot verify scientific accuracy,")
    print("        text inside images, or whether citations are real. Human review")
    print("        of the slides is still required.\n")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"pdf": pdf, "pages": n_pages, "speller": engine,
                       "counts": counts, "findings": findings}, fh, indent=2)

    if args.strict and any(f["severity"] in ("high", "medium") for f in findings):
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, ET.ParseError, subprocess.CalledProcessError) as exc:
        sys.exit(f"error: {exc}")
