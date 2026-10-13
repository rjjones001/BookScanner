# Scan2Book (Phase 1 vertical slice)

Upload a scanned PDF -> OCR + structure detection -> XeLaTeX typesetting -> downloadable, searchable PDF,
with a review queue for uncertain text. Everything below was run and tested unless marked otherwise.

## Run locally
System packages (Ubuntu/Debian): `tesseract-ocr tesseract-ocr-osd texlive-xetex texlive-latex-extra fonts-lmodern tex-gyre fonts-dejavu-core`
```
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload          # http://localhost:8000
pytest -q tests                        # builds synthetic image-only PDFs and runs the real pipeline
```
Docker: `docker build -t scan2book . && docker run -p 8000:8000 -v s2b:/data scan2book`

## Status
| Feature | Status |
|---|---|
| PDF validation, limits, render, rotation + skew fix | Implemented and tested |
| Printed-text OCR (Tesseract, confidences) | Implemented and tested on synthetic scans only |
| Textbook / PYQ structure (headings, questions, options, bullets; labels kept verbatim) | Implemented and tested (heuristic) |
| Figure preservation (unreadable ink kept as image crops; failed pages kept as images) | Implemented and tested |
| XeLaTeX typesetting, equations from LaTeX, page size/font/size options, headers/page numbers | Implemented and tested |
| Output validation (opens, text layer recall, blank/clipped pages, missing glyphs) | Implemented and tested |
| Review queue, edit, regenerate, history, delete, cancel/retry, retention, owner-cookie isolation | Implemented and tested |
| Markdown export | Implemented |
| AI suggestions for uncertain crops (`ANTHROPIC_API_KEY`) | Implemented, **untested** (needs your key; sends crops to Anthropic) |
| **Math recognition from scans** (image -> LaTeX) | **Not implemented.** Typesetter renders LaTeX correctly, but nothing yet produces it. Next: Pix2Text / Mathpix / vision model |
| **Handwriting recognition** | **Not reliable.** Tesseract is poor at it; regions are flagged. Needs a handwriting-capable model |
| Tables (rebuild), vector redrawing of diagrams, DOCX export, Next.js frontend, Celery/Redis, PostgreSQL, real auth | Not implemented (SQLite + thread pool + vanilla UI used instead) |

## Limits to know
- Math in scans currently comes out as garbled plain text with low confidence - review it. Never trust it unreviewed.
- No accuracy figure is claimed; only synthetic clean scans were tested. Test on your own documents.
- Owner cookie is not authentication. Put real auth/HTTPS in front before exposing publicly.
- Page breaks reflow (source page numbers are kept in the LaTeX comments and IR, not the layout).
- Hyphenation is disabled so text stays searchable; "do not change wording" means no de-hyphenation of OCR line ends either.
