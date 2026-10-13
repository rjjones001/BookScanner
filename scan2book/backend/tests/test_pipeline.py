import re
import time
from collections import Counter
import pymupdf
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from app import config, typeset, validate
from app.ir import Block, Doc, Page
from app.main import app
from app.ocr import RawLine, RawPara, RawWord
from app.structure import build_blocks
from tests import make_samples as ms

TOK = re.compile(r"\w+")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def run_job(client, pdf_path, **form):
    with open(pdf_path, "rb") as f:
        r = client.post("/api/jobs", files={"file": ("sample.pdf", f, "application/pdf")}, data=form)
    assert r.status_code == 200, r.text
    jid = r.json()["id"]
    for _ in range(240):
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("done", "failed", "cancelled"):
            break
        time.sleep(1)
    assert j["status"] == "done", j
    return jid, j


def recall(expected, pdf_bytes):
    d = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    got = Counter(t.lower() for p in d for t in TOK.findall(p.get_text()))
    exp = Counter(t.lower() for w in expected for t in TOK.findall(w))
    return sum(min(n, got[t]) for t, n in exp.items()) / sum(exp.values()), d


def test_textbook_end_to_end(client, tmp_path):
    im, words = ms.textbook_page()
    pdf = ms.to_pdf([im], tmp_path / "tb.pdf")
    jid, job = run_job(client, pdf, mode="textbook")
    assert job["pages_done"] == 1 and job["pages_failed"] == 0
    out = client.get(f"/api/jobs/{jid}/pdf")
    assert out.status_code == 200 and out.content[:5] == b"%PDF-"
    r, d = recall(words, out.content)
    assert r >= 0.95, r                                  # searchable, selectable text layer
    ir = client.get(f"/api/jobs/{jid}/ir").json()
    kinds = [b["kind"] for b in ir["pages"][0]["blocks"]]
    assert kinds[0] == "heading" and "paragraph" in kinds


def test_pyq_structure_preserved(client, tmp_path):
    pdf = ms.to_pdf([ms.pyq_page()], tmp_path / "pyq.pdf")
    jid, _ = run_job(client, pdf, mode="pyq")
    blocks = client.get(f"/api/jobs/{jid}/ir").json()["pages"][0]["blocks"]
    labels = [(b["kind"], b["label"]) for b in blocks]
    assert labels.count(("question", "1.")) == 1 and labels.count(("question", "2.")) == 1
    assert [l for k, l in labels if k == "option"][:4] == ["(A)", "(B)", "(C)", "(D)"]
    assert "Newton" in " ".join(b["text"] for b in blocks)


def test_figure_preserved_not_dropped(client, tmp_path):
    pdf = ms.to_pdf([ms.figure_page()], tmp_path / "fig.pdf")
    jid, _ = run_job(client, pdf, mode="textbook")
    blocks = client.get(f"/api/jobs/{jid}/ir").json()["pages"][0]["blocks"]
    assert any(b["kind"] == "figure" for b in blocks)
    d = pymupdf.open(stream=client.get(f"/api/jobs/{jid}/pdf").content, filetype="pdf")
    assert sum(len(p.get_images()) for p in d) >= 1


def test_rotated_and_skewed_scans(client, tmp_path):
    im, words = ms.textbook_page()
    rot = im.rotate(90, expand=True, fillcolor="white")
    skew = im.rotate(2.0, fillcolor="white")
    pdf = ms.to_pdf([rot, skew], tmp_path / "rot.pdf")
    jid, job = run_job(client, pdf, mode="textbook", quality="advanced")
    assert job["pages_done"] == 2
    out = client.get(f"/api/jobs/{jid}/pdf").content
    r, _ = recall(words * 2, out)
    assert r >= 0.85, r


def test_review_edit_and_rebuild(client, tmp_path):
    pdf = ms.to_pdf([ms.pyq_page()], tmp_path / "e.pdf")
    jid, _ = run_job(client, pdf, mode="pyq")
    ir = client.get(f"/api/jobs/{jid}/ir").json()
    bid = next(b["id"] for b in ir["pages"][0]["blocks"] if b["kind"] == "question")
    assert client.put(f"/api/jobs/{jid}/blocks/{bid}", json={"text": "Corrected sentinel text zebra"}).status_code == 200
    assert client.post(f"/api/jobs/{jid}/rebuild").status_code == 200
    for _ in range(120):
        if client.get(f"/api/jobs/{jid}").json()["status"] == "done":
            break
        time.sleep(1)
    d = pymupdf.open(stream=client.get(f"/api/jobs/{jid}/pdf").content, filetype="pdf")
    assert "zebra" in "".join(p.get_text() for p in d)


def test_upload_rejections_and_isolation(client, tmp_path):
    r = client.post("/api/jobs", files={"file": ("x.pdf", b"not a pdf", "application/pdf")})
    assert r.status_code == 400
    pdf = ms.to_pdf([ms.pyq_page()], tmp_path / "iso.pdf")
    jid, _ = run_job(client, pdf, mode="pyq")
    other = TestClient(app)                                  # different cookie jar = different owner
    assert other.get(f"/api/jobs/{jid}").status_code == 404
    assert other.get(f"/api/jobs/{jid}/pdf").status_code == 404
    assert client.get("/api/jobs/../../etc/passwd/pdf").status_code in (404, 405)


def test_invalid_options_rejected(client, tmp_path):
    pdf = ms.to_pdf([ms.pyq_page()], tmp_path / "o.pdf")
    with open(pdf, "rb") as f:
        r = client.post("/api/jobs", files={"file": ("a.pdf", f, "application/pdf")}, data={"font": "../../x"})
    assert r.status_code == 400


# ---------- unit tests ----------
def test_latex_escaping():
    assert typeset.esc("50% of $x & y_1 #") == r"50\% of \$x \& y\_1 \#"


def test_equation_typesetting_and_unsafe_fallback(tmp_path):
    doc = Doc(title="Eq", pages=[Page(number=1, blocks=[
        Block(id="e1", kind="equation", latex=r"\int_0^1 \frac{x^2}{\sqrt{1+x}}\,dx = \sum_{n=1}^{\infty}\alpha_n"),
        Block(id="e2", kind="equation", latex=r"\input{/etc/passwd}"),
        Block(id="e3", kind="paragraph", text="after equations"),
    ])])
    tex, warns = typeset.to_latex(doc, tmp_path)
    eq2 = tex.split("% block e2")[1].split("% block e3")[0]
    assert "\\input" not in eq2.replace("\\textbackslash{}input", "")
    assert any("unsafe" in w for w in warns)
    pdf, log = typeset.compile_pdf(tex, tmp_path)
    d = pymupdf.open(pdf)
    assert d.page_count == 1 and "after equations" in d[0].get_text()
    assert validate.validate(pdf, doc, log) == []


def _line(text, h=30, conf=0.95):
    return RawLine(words=[RawWord(t, conf, 10 + i * 50, 10, 40, h) for i, t in enumerate(text.split())])


def test_structure_labels_verbatim_and_low_conf_flagged():
    paras = [RawPara(lines=[_line("12. Find the value of x"), _line("if 3x = 9", conf=0.3)]),
             RawPara(lines=[_line("(B) six"), _line("(c) nine")])]
    blocks = build_blocks(paras, "pyq", 1)
    assert [(b.kind, b.label) for b in blocks] == [("question", "12."), ("option", "(B)"), ("option", "(c)")]
    assert blocks[0].text.endswith("if 3x = 9") and blocks[0].low_words      # wording untouched, uncertainty recorded
