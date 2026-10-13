"""Orchestrates stages 1-6 for one job and records real progress in the DB."""
from __future__ import annotations
import json
import logging
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import numpy as np
import pymupdf
from PIL import Image
from . import config, db, figures, ingest, structure, typeset, validate, vision
from .ir import Block, Doc, Page, from_dict, to_dict
from .ocr import TesseractEngine

log = logging.getLogger("pipeline")   # never log document text
ENGINE = TesseractEngine()


def job_dir(job_id: str) -> Path:
    return config.DATA_DIR / "jobs" / job_id


def _save_img(img: Image.Image, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def process_page(jd: Path, idx: int, p: dict) -> Page:
    q = config.QUALITY[p["quality"]]
    n = idx + 1
    doc = pymupdf.open(jd / "source.pdf")
    page = doc[idx]
    pg = Page(number=n)
    if not p.get("force_ocr") and ingest.embedded_words(page) >= 20:
        img = ingest.render(page, 150)
        pg.source, pg.width, pg.height = "embedded", img.width, img.height
        pg.image = f"pages/p{n:04d}.png"
        _save_img(img, jd / pg.image)
        s = 150 / 72.0
        for i, b in enumerate(sorted(page.get_text("blocks"), key=lambda b: (round(b[1] / 8), b[0]))):
            if b[6] != 0 or not b[4].strip():
                continue
            pg.blocks.append(Block(id=f"p{n}b{i + 1}", kind="paragraph", text=" ".join(b[4].split()),
                                   bbox=[int(b[0] * s), int(b[1] * s), int(b[2] * s), int(b[3] * s)]))
        pg.warnings.append("Used the existing PDF text layer (tick 'Force OCR' to re-recognise the scan)")
        return pg

    img = ingest.render(page, q["dpi"])
    img, rot = ingest.fix_orientation(img)
    if rot:
        pg.warnings.append(f"Page rotated by {rot} degrees")
    if q["deskew"]:
        img, ang = ingest.deskew(img)
        if ang:
            pg.warnings.append(f"Skew corrected by {ang:.2f} degrees")
    pg.width, pg.height = img.size
    pg.image = f"pages/p{n:04d}.png"
    _save_img(img, jd / pg.image)

    paras = ENGINE.recognize(img)
    figs = figures.detect(img, paras)
    moved = 0
    for fb in figs:                    # low-confidence words inside a figure belong to the figure
        for para in paras:
            for ln in para.lines:
                keep = [w for w in ln.words if not (w.conf < config.LOW_CONF and figures.inside(fb, w))]
                moved += len(ln.words) - len(keep)
                ln.words = keep
    if moved:
        pg.warnings.append(f"{moved} low-confidence words fall inside figure regions and are kept in the figure image")
    paras = [pp for pp in paras if any(ln.words for ln in pp.lines)]
    blocks = structure.build_blocks(paras, p["mode"], n)

    for k, fb in enumerate(figs):
        rel = f"crops/p{n:04d}f{k + 1}.png"
        _save_img(img.crop(tuple(fb)), jd / rel)
        fblock = Block(id=f"p{n}f{k + 1}", kind="figure", image=rel, bbox=fb)
        at = next((i for i, b in enumerate(blocks) if b.bbox and b.bbox[1] >= fb[1]), len(blocks))
        blocks.insert(at, fblock)
    if figs:
        pg.warnings.append(f"{len(figs)} figure/unreadable region(s) preserved as images (not interpreted)")

    if not blocks:
        ink = (np.array(img.convert("L")) < 128).mean()
        if ink < 0.002:
            pg.warnings.append("Page appears blank")
        else:
            rel = f"crops/p{n:04d}full.png"
            _save_img(img, jd / rel)
            blocks.append(Block(id=f"p{n}f1", kind="figure", image=rel, bbox=[0, 0, img.width, img.height]))
            pg.warnings.append("No text recognised; whole page preserved as an image for manual transcription")

    if q["vision"] and p.get("handwriting") and vision.enabled():
        for b in [b for b in blocks if b.kind != "figure" and b.conf < config.LOW_CONF][:15]:
            try:
                x0, y0, x1, y1 = b.bbox
                b.suggestion = vision.transcribe(img.crop((max(0, x0 - 10), max(0, y0 - 10), x1 + 10, y1 + 10)))
            except Exception as e:  # provider failure must not fail the page
                pg.warnings.append(f"AI suggestion failed for {b.id}: {type(e).__name__}")
                break
    pg.blocks = blocks
    return pg


def build_output(job_id: str, doc: Doc, p: dict) -> list[str]:
    jd = job_dir(job_id)
    kw = dict(page_size=p["page_size"], font=p["font"], size=p["font_size"], q_gap_pt=p.get("question_gap", 8))
    tex, w = typeset.to_latex(doc, jd, **kw)
    try:
        pdf, lg = typeset.compile_pdf(tex, jd / "build")
    except RuntimeError as e:
        # one bad formula must not block the document: retry with equations as plain text, and say so
        tex, w2 = typeset.to_latex(doc, jd, equations_as_math=False, **kw)
        pdf, lg = typeset.compile_pdf(tex, jd / "build")
        w = w2 + ["A LaTeX error occurred; equations were printed as plain text: " + str(e)[:200]]
    (jd / "output.pdf").write_bytes(pdf.read_bytes())
    (jd / "output.md").write_text(typeset.to_markdown(doc), encoding="utf-8")
    return w + validate.validate(jd / "output.pdf", doc, lg)


def save_ir(job_id: str, doc: Doc):
    (job_dir(job_id) / "ir.json").write_text(json.dumps(to_dict(doc)), encoding="utf-8")


def load_ir(job_id: str) -> Doc:
    return from_dict(json.loads((job_dir(job_id) / "ir.json").read_text(encoding="utf-8")))


def _guarded(job_id, jd, i, p):
    if (db.get(job_id) or {}).get("cancel"):
        return None
    try:
        return process_page(jd, i, p)
    except Exception as e:
        # never drop a page silently: keep the raw page as an image and flag it
        pg = Page(number=i + 1, failed=True, warnings=[f"Recognition failed ({type(e).__name__}); page kept as image"])
        try:
            img = ingest.render(pymupdf.open(jd / "source.pdf")[i], 150)
            rel = f"crops/p{i + 1:04d}full.png"
            _save_img(img, jd / rel)
            pg.image = rel
            pg.width, pg.height = img.size
            pg.blocks = [Block(id=f"p{i + 1}f1", kind="figure", image=rel, bbox=[0, 0, img.width, img.height])]
        except Exception:
            pass
        return pg


def run(job_id: str):
    job = db.get(job_id)
    if not job:
        return
    p, jd = job["params"], job_dir(job_id)
    warnings: list[str] = []
    try:
        db.update(job_id, status="running", stage="ingest")
        d = ingest.open_pdf(str(jd / "source.pdf"), config.MAX_PAGES)
        total = d.page_count
        d.close()
        if p.get("handwriting") and not (vision.enabled() and config.QUALITY[p["quality"]]["vision"]):
            warnings.append("Handwriting option is on, but no AI transcription is available (needs Advanced/High "
                            "quality and ANTHROPIC_API_KEY). Tesseract reads handwriting poorly, so uncertain "
                            "regions are flagged for manual review.")
        db.update(job_id, stage="recognition", pages_total=total, warnings=warnings)
        results: dict[int, Page] = {}
        with ThreadPoolExecutor(config.PAGE_WORKERS) as ex:
            futs = {ex.submit(_guarded, job_id, jd, i, p): i for i in range(total)}
            for f in as_completed(futs):
                pg = f.result()
                if pg is None:      # cancelled
                    continue
                results[futs[f]] = pg
                db.incr(job_id, "pages_failed" if pg.failed else "pages_done")
        if (db.get(job_id) or {}).get("cancel"):
            db.update(job_id, status="cancelled", stage="cancelled")
            return
        doc = Doc(title=Path(job["filename"]).stem, mode=p["mode"], pages=[results[i] for i in sorted(results)])
        for pg in doc.pages:
            warnings += [f"Page {pg.number}: {w}" for w in pg.warnings]
        save_ir(job_id, doc)
        db.update(job_id, stage="typesetting", warnings=warnings)
        warnings += build_output(job_id, doc, p)
        db.update(job_id, status="done", stage="done", warnings=warnings)
    except Exception as e:
        log.error("job %s failed: %s", job_id, traceback.format_exc())
        db.update(job_id, status="failed", error=str(e)[:500], warnings=warnings)


def rebuild(job_id: str):
    job = db.get(job_id)
    try:
        db.update(job_id, status="running", stage="typesetting", error="")
        doc = load_ir(job_id)
        ws = [w for w in job["warnings"] if w.startswith("Page ") or w.startswith("Handwriting")]
        ws += build_output(job_id, doc, job["params"])
        db.update(job_id, status="done", stage="done", warnings=ws)
    except Exception as e:
        db.update(job_id, status="failed", error=str(e)[:500])
