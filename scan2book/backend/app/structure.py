"""Stage 4: turn raw OCR paragraphs into typed IR blocks. Wording is never altered:
labels are kept verbatim, no de-hyphenation, no spelling correction."""
from __future__ import annotations
import re
import statistics
from . import config
from .ir import Block

QRE = re.compile(r"^\s*((?:Q(?:uestion)?\.?\s*)?\d{1,3}\s*[.)])\s+(.*)$", re.I)
ORE = re.compile(r"^\s*(\([A-Da-d1-4]\)|[A-Da-d][.)])\s+(.*)$")
BRE = re.compile(r"^\s*([•·▪●■\-–*])\s+(.*)$")


def _line_text(ln) -> str:
    return " ".join(w.text for w in ln.words)


def _bbox(words):
    return [min(w.x for w in words), min(w.y for w in words),
            max(w.x + w.w for w in words), max(w.y + w.h for w in words)]


def _finish(blk: Block, words: list) -> Block:
    if words:
        blk.conf = round(sum(w.conf for w in words) / len(words), 3)
        blk.bbox = _bbox(words)
        blk.low_words = [{"text": w.text, "conf": round(w.conf, 2)} for w in words if w.conf < config.LOW_CONF]
    return blk


def build_blocks(paras: list, mode: str, page_no: int) -> list[Block]:
    heights = [wd.h for p in paras for ln in p.lines for wd in ln.words]
    med = statistics.median(heights) if heights else 20
    blocks: list[Block] = []
    n = 0

    def new(kind, label, text, words, **kw):
        nonlocal n
        n += 1
        b = Block(id=f"p{page_no}b{n}", kind=kind, label=label, text=text, **kw)
        blocks.append(b)
        return b, list(words)

    for p in paras:
        cur = None            # (block, words)
        for idx, ln in enumerate(p.lines):
            if not ln.words:
                continue
            txt = _line_text(ln)
            lh = statistics.median([w.h for w in ln.words])
            # headings (textbook mode, size-based heuristic, flagged as inferred)
            if (mode == "textbook" and len(p.lines) <= 2 and len(txt) <= 100
                    and lh >= 1.35 * med and not txt.endswith((".", ",", ";"))):
                if cur: _finish(*cur)
                cur = new("heading", "", txt, ln.words, level=1 if lh >= 1.8 * med else 2, inferred=True)
                continue
            m = None
            if mode == "pyq":
                m = (ORE.match(txt) and ("option", ORE.match(txt))) or (QRE.match(txt) and ("question", QRE.match(txt)))
            else:
                bm = BRE.match(txt)
                m = bm and ("list_item", bm)
            if m:
                kind, mm = m
                if cur: _finish(*cur)
                cur = new(kind, mm.group(1).strip(), mm.group(2).strip(), ln.words)
            elif cur and cur[0].kind != "heading":
                cur[0].text += " " + txt
                cur[1].extend(ln.words)
            else:
                if cur: _finish(*cur)
                cur = new("paragraph", "", txt, ln.words)
        if cur: _finish(*cur)
    return blocks
