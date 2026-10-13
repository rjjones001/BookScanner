"""FastAPI app. Access control here is a per-browser owner cookie (enough to keep one user's jobs
away from another's, NOT real authentication - put real auth in front before exposing publicly)."""
from __future__ import annotations
import re
import shutil
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from . import config, db, ingest, pipeline, typeset, vision
from .ir import to_dict

app = FastAPI(title="Scan2Book", docs_url="/api/docs", redoc_url=None)
executor = ThreadPoolExecutor(config.JOB_WORKERS)
STATIC = Path(__file__).parent / "static"


@app.on_event("startup")
def _startup():
    db.init()
    purge_expired()


def purge_expired():
    cutoff = time.time() - config.RETENTION_DAYS * 86400
    for jid in db.expired(cutoff):
        shutil.rmtree(pipeline.job_dir(jid), ignore_errors=True)
        db.delete(jid)


def owner_dep(request: Request, response: Response) -> str:
    oid = request.cookies.get("owner_id", "")
    if not re.fullmatch(r"[0-9a-f]{32}", oid):
        oid = uuid.uuid4().hex
        response.set_cookie("owner_id", oid, httponly=True, samesite="lax", max_age=365 * 86400)
    return oid


def get_job(job_id: str, owner: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise HTTPException(404, "Not found")
    j = db.get(job_id, owner)
    if not j:
        raise HTTPException(404, "Not found")
    return j


def public(j: dict) -> dict:
    return {k: j[k] for k in ("id", "filename", "status", "stage", "params", "pages_total", "pages_done",
                              "pages_failed", "warnings", "error", "created", "updated")}


@app.get("/api/config")
def cfg():
    return {"max_upload_mb": config.MAX_UPLOAD_MB, "max_pages": config.MAX_PAGES,
            "retention_days": config.RETENTION_DAYS, "fonts": list(typeset.installed_fonts()),
            "page_sizes": list(config.PAGE_SIZES), "ai_transcription_enabled": vision.enabled(),
            "ocr_engine": "tesseract (runs on this server)",
            "third_party_disclosure": ("Crops of uncertain regions are sent to Anthropic's API when quality is "
                                       "Advanced/High and handwriting is enabled." if vision.enabled() else
                                       "No document data leaves this server.")}


@app.post("/api/jobs")
async def create_job(file: UploadFile = File(...), mode: str = Form("textbook"), page_size: str = Form("a4"),
                     font: str = Form("serif"), font_size: int = Form(11), quality: str = Form("standard"),
                     handwriting: bool = Form(False), force_ocr: bool = Form(False),
                     question_gap: int = Form(8), owner: str = Depends(owner_dep)):
    if mode not in config.MODES or page_size not in config.PAGE_SIZES or quality not in config.QUALITY \
            or font_size not in config.FONT_SIZES or font not in config.FONTS or not 0 <= question_gap <= 40:
        raise HTTPException(400, "Invalid option")
    purge_expired()
    job_id = uuid.uuid4().hex
    jd = pipeline.job_dir(job_id)
    jd.mkdir(parents=True)
    src, size, limit = jd / "source.pdf", 0, config.MAX_UPLOAD_MB * 1024 * 1024
    with open(src, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                shutil.rmtree(jd, ignore_errors=True)
                raise HTTPException(413, f"File exceeds {config.MAX_UPLOAD_MB} MB")
            out.write(chunk)
    try:
        if src.read_bytes()[:5] != b"%PDF-":
            raise ValueError("File is not a PDF")
        d = ingest.open_pdf(str(src), config.MAX_PAGES)
        pages = d.page_count
        d.close()
    except ValueError as e:
        shutil.rmtree(jd, ignore_errors=True)
        raise HTTPException(400, str(e))
    params = dict(mode=mode, page_size=page_size, font=font, font_size=font_size, quality=quality,
                  handwriting=handwriting, force_ocr=force_ocr, question_gap=question_gap)
    name = re.sub(r"[^\w.\- ]", "_", file.filename or "document.pdf")[:120]
    db.create(job_id, owner, name, params, pages)
    executor.submit(pipeline.run, job_id)
    return {"id": job_id, "pages": pages}


@app.get("/api/jobs")
def list_jobs(owner: str = Depends(owner_dep)):
    return [public(j) for j in db.list_for(owner)]


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str, owner: str = Depends(owner_dep)):
    return public(get_job(job_id, owner))


@app.post("/api/jobs/{job_id}/cancel")
def cancel(job_id: str, owner: str = Depends(owner_dep)):
    get_job(job_id, owner)
    db.update(job_id, cancel=1)
    return {"ok": True}


@app.post("/api/jobs/{job_id}/retry")
def retry(job_id: str, owner: str = Depends(owner_dep)):
    j = get_job(job_id, owner)
    if j["status"] in ("running", "queued"):
        raise HTTPException(409, "Job is still running")
    db.update(job_id, cancel=0, status="queued", stage="queued", pages_done=0, pages_failed=0, error="")
    executor.submit(pipeline.run, job_id)
    return {"ok": True}


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str, owner: str = Depends(owner_dep)):
    j = get_job(job_id, owner)
    if j["status"] in ("running", "queued"):
        db.update(job_id, cancel=1)
        raise HTTPException(409, "Job is running; cancellation requested - delete again when it stops")
    shutil.rmtree(pipeline.job_dir(job_id), ignore_errors=True)
    db.delete(job_id)
    return {"ok": True}


def _file(job_id: str, owner: str, rel: str, media: str, name: str | None = None):
    j = get_job(job_id, owner)
    p = pipeline.job_dir(job_id) / rel
    if not p.exists():
        raise HTTPException(404, "Not available yet")
    return FileResponse(p, media_type=media, filename=name or None)


@app.get("/api/jobs/{job_id}/pdf")
def dl_pdf(job_id: str, owner: str = Depends(owner_dep)):
    j = get_job(job_id, owner)
    return _file(job_id, owner, "output.pdf", "application/pdf", Path(j["filename"]).stem + "-typeset.pdf")


@app.get("/api/jobs/{job_id}/markdown")
def dl_md(job_id: str, owner: str = Depends(owner_dep)):
    j = get_job(job_id, owner)
    return _file(job_id, owner, "output.md", "text/markdown", Path(j["filename"]).stem + ".md")


@app.get("/api/jobs/{job_id}/source")
def dl_src(job_id: str, owner: str = Depends(owner_dep)):
    return _file(job_id, owner, "source.pdf", "application/pdf")


@app.get("/api/jobs/{job_id}/ir")
def ir(job_id: str, owner: str = Depends(owner_dep)):
    get_job(job_id, owner)
    try:
        return to_dict(pipeline.load_ir(job_id))
    except FileNotFoundError:
        raise HTTPException(404, "Not available yet")


@app.get("/api/jobs/{job_id}/pages/{n}/image")
def page_image(job_id: str, n: int, owner: str = Depends(owner_dep)):
    return _file(job_id, owner, f"pages/p{int(n):04d}.png", "image/png")


@app.get("/api/jobs/{job_id}/blocks/{block_id}/crop")
def block_crop(job_id: str, block_id: str, owner: str = Depends(owner_dep)):
    get_job(job_id, owner)
    doc = pipeline.load_ir(job_id)
    for pg in doc.pages:
        for b in pg.blocks:
            if b.id == block_id and b.bbox and pg.image:
                im = Image.open(pipeline.job_dir(job_id) / pg.image)
                x0, y0, x1, y1 = b.bbox
                crop = im.crop((max(0, x0 - 12), max(0, y0 - 12), min(im.width, x1 + 12), min(im.height, y1 + 12)))
                out = pipeline.job_dir(job_id) / "crops" / f"review_{b.id}.png"
                out.parent.mkdir(exist_ok=True)
                crop.save(out)
                return FileResponse(out, media_type="image/png")
    raise HTTPException(404, "Not found")


@app.get("/api/jobs/{job_id}/crops/{name}")
def figure_img(job_id: str, name: str, owner: str = Depends(owner_dep)):
    if not re.fullmatch(r"[\w\-]+\.png", name):
        raise HTTPException(404, "Not found")
    return _file(job_id, owner, f"crops/{name}", "image/png")


@app.get("/api/jobs/{job_id}/review")
def review_queue(job_id: str, owner: str = Depends(owner_dep)):
    get_job(job_id, owner)
    try:
        doc = pipeline.load_ir(job_id)
    except FileNotFoundError:
        return []
    return [{"page": pg.number, "block": b.id, "kind": b.kind, "text": b.text, "latex": b.latex, "conf": b.conf,
             "low_words": b.low_words, "suggestion": b.suggestion}
            for pg in doc.pages for b in pg.blocks
            if b.kind != "figure" and not b.reviewed and (b.conf < config.LOW_CONF or b.low_words)]


@app.put("/api/jobs/{job_id}/blocks/{block_id}")
async def edit_block(job_id: str, block_id: str, request: Request, owner: str = Depends(owner_dep)):
    j = get_job(job_id, owner)
    if j["status"] in ("running", "queued"):
        raise HTTPException(409, "Job is running")
    body = await request.json()
    doc = pipeline.load_ir(job_id)
    for pg in doc.pages:
        for b in pg.blocks:
            if b.id == block_id:
                if isinstance(body.get("text"), str):
                    b.text = body["text"][:20000]
                if isinstance(body.get("latex"), str):
                    b.latex = body["latex"][:5000]
                if body.get("kind") in ("paragraph", "heading", "question", "option", "list_item", "equation"):
                    b.kind = body["kind"]
                b.reviewed = True
                pipeline.save_ir(job_id, doc)
                return {"ok": True}
    raise HTTPException(404, "Block not found")


@app.post("/api/jobs/{job_id}/rebuild")
def rebuild(job_id: str, owner: str = Depends(owner_dep)):
    j = get_job(job_id, owner)
    if j["status"] in ("running", "queued"):
        raise HTTPException(409, "Job is running")
    db.update(job_id, status="queued", stage="typesetting")
    executor.submit(pipeline.rebuild, job_id)
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
