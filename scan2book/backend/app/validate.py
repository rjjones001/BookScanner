"""Stage 6: independent checks on the generated PDF. A successful compile is not proof of correctness."""
from __future__ import annotations
import re
from collections import Counter
from pathlib import Path
import pymupdf
from .ir import Doc

TOK = re.compile(r"\w+", re.U)


def expected_tokens(doc: Doc) -> Counter:
    c: Counter = Counter()
    for pg in doc.pages:
        for b in pg.blocks:
            if b.kind in ("figure", "equation"):
                continue
            c.update(t.lower() for t in TOK.findall(f"{b.label} {b.text}"))
    return c


def validate(pdf: Path, doc: Doc, log: str = "") -> list[str]:
    w: list[str] = []
    try:
        pd = pymupdf.open(pdf)
    except Exception as e:
        return [f"Generated PDF cannot be opened: {e}"]
    if pd.page_count == 0:
        return ["Generated PDF has no pages"]
    got: Counter = Counter()
    for i, page in enumerate(pd):
        txt = page.get_text()
        got.update(t.lower() for t in TOK.findall(txt))
        if not txt.strip() and not page.get_images():
            w.append(f"Output page {i + 1} appears blank")
        r = page.rect
        for bx in page.get_text("blocks"):
            if bx[0] < -1 or bx[1] < -1 or bx[2] > r.width + 1 or bx[3] > r.height + 1:
                w.append(f"Content on output page {i + 1} extends beyond the page")
                break
    exp = expected_tokens(doc)
    total = sum(exp.values())
    if total:
        recall = sum(min(n, got[t]) for t, n in exp.items()) / total
        if recall < 0.98:
            w.append(f"Only {recall:.1%} of recognised words were found in the output PDF text layer")
    if "Missing character" in log:
        w.append("Some characters are missing from the chosen font (see LaTeX log)")
    figs = sum(1 for pg in doc.pages for b in pg.blocks if b.kind == "figure")
    if figs and sum(len(p.get_images()) for p in pd) < 1:
        w.append("Figures were expected in the output but no images were found")
    return w
