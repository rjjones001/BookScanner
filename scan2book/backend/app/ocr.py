"""Stage 3: recognition engines. Engines are swappable: implement `recognize(img) -> list[RawPara]`.
Tesseract is the only engine that ships working; it handles printed text well and handwriting poorly,
so low-confidence output is flagged for review rather than trusted."""
from __future__ import annotations
from dataclasses import dataclass, field
import pytesseract
from PIL import Image
from . import config


@dataclass
class RawWord:
    text: str
    conf: float          # 0..1
    x: int
    y: int
    w: int
    h: int


@dataclass
class RawLine:
    words: list = field(default_factory=list)


@dataclass
class RawPara:
    lines: list = field(default_factory=list)


class TesseractEngine:
    name = "tesseract"

    def recognize(self, img: Image.Image) -> list[RawPara]:
        d = pytesseract.image_to_data(
            img, lang=config.TESS_LANG, config="--psm 3",
            output_type=pytesseract.Output.DICT, timeout=config.TESS_TIMEOUT)
        paras: dict = {}
        order: list = []
        for i in range(len(d["text"])):
            txt = (d["text"][i] or "").strip()
            conf = float(d["conf"][i])
            if not txt or conf < 0:
                continue
            key = (d["block_num"][i], d["par_num"][i])
            lkey = d["line_num"][i]
            if key not in paras:
                paras[key] = {}
                order.append(key)
            paras[key].setdefault(lkey, []).append(
                RawWord(txt, conf / 100.0, d["left"][i], d["top"][i], d["width"][i], d["height"][i]))
        out = []
        for key in order:
            p = RawPara()
            for lk in sorted(paras[key]):
                p.lines.append(RawLine(words=sorted(paras[key][lk], key=lambda w: w.x)))
            out.append(p)
        return out
