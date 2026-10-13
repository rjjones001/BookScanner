"""Stage 1: PDF validation, rendering, orientation + skew correction."""
from __future__ import annotations
import cv2
import numpy as np
import pymupdf
import pytesseract
from PIL import Image


def open_pdf(path: str, max_pages: int) -> pymupdf.Document:
    try:
        doc = pymupdf.open(path)
    except Exception as e:  # corrupt / not a PDF
        raise ValueError("File is not a readable PDF") from e
    if doc.needs_pass:
        raise ValueError("Encrypted PDFs are not supported")
    if doc.page_count == 0:
        raise ValueError("PDF has no pages")
    if doc.page_count > max_pages:
        raise ValueError(f"PDF has {doc.page_count} pages; the configured limit is {max_pages}")
    return doc


def embedded_words(page: pymupdf.Page) -> int:
    return len(page.get_text("words"))


def render(page: pymupdf.Page, dpi: int) -> Image.Image:
    pix = page.get_pixmap(dpi=dpi, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def fix_orientation(img: Image.Image) -> tuple[Image.Image, int]:
    """Rotate by 90/180/270 if Tesseract OSD is confident. Returns (image, degrees_applied)."""
    try:
        osd = pytesseract.image_to_osd(img, output_type=pytesseract.Output.DICT, timeout=60)
        rot = int(osd.get("rotate", 0))
        if rot and float(osd.get("orientation_conf", 0)) >= 2.0:
            return img.rotate(-rot, expand=True, fillcolor="white"), rot
    except Exception:
        pass
    return img, 0


def _rotate(arr: np.ndarray, angle: float, border) -> np.ndarray:
    h, w = arr.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(arr, m, (w, h), flags=cv2.INTER_CUBIC, borderValue=border)


def deskew(img: Image.Image, max_angle: float = 8.0) -> tuple[Image.Image, float]:
    """Projection-profile skew search on a downscaled binary image."""
    gray = np.array(img.convert("L"))
    scale = 800.0 / max(gray.shape)
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    bw = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    if cv2.countNonZero(bw) < 300:
        return img, 0.0
    best, best_score = 0.0, -1.0
    for a in np.arange(-max_angle, max_angle + 0.01, 0.25):
        score = float(np.var(_rotate(bw, a, 0).sum(axis=1)))
        if score > best_score:
            best, best_score = float(a), score
    if abs(best) < 0.3:
        return img, 0.0
    out = _rotate(np.array(img.convert("RGB")), best, (255, 255, 255))
    return Image.fromarray(out), best
