"""Intermediate representation (IR). Every block keeps its page, bbox and confidence
so the review UI can always show the original region next to the reconstruction."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Block:
    id: str
    kind: str                 # heading|paragraph|question|option|list_item|equation|figure
    text: str = ""
    latex: str = ""           # for kind == equation
    label: str = ""           # verbatim label as printed: "12.", "(A)", "•"
    level: int = 1            # heading level
    conf: float = 1.0         # 0..1, mean word confidence (1.0 for embedded text / figures)
    bbox: list = field(default_factory=list)   # [x0,y0,x1,y1] in page-image pixels
    image: str = ""           # relative path (figures)
    inferred: bool = False    # structure (e.g. heading) guessed by heuristics
    low_words: list = field(default_factory=list)   # [{"text":..,"conf":..}]
    suggestion: str = ""      # optional AI suggestion; NEVER applied automatically
    reviewed: bool = False    # user confirmed or edited


@dataclass
class Page:
    number: int
    width: int = 0
    height: int = 0
    source: str = "scanned"   # scanned | embedded
    image: str = ""
    blocks: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    failed: bool = False


@dataclass
class Doc:
    title: str = ""
    mode: str = "textbook"
    pages: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def to_dict(doc: Doc) -> dict[str, Any]:
    return asdict(doc)


def from_dict(d: dict) -> Doc:
    pages = []
    for p in d.get("pages", []):
        p = dict(p)
        p["blocks"] = [Block(**b) for b in p.get("blocks", [])]
        pages.append(Page(**p))
    return Doc(title=d.get("title", ""), mode=d.get("mode", "textbook"),
               pages=pages, warnings=d.get("warnings", []))
