"""Figure detection: ink that is NOT explained by confidently recognised text becomes a figure crop.
Anything the OCR cannot read (diagrams, handwriting, stamps) is therefore preserved as an image
instead of being silently dropped."""
from __future__ import annotations
import cv2
import numpy as np
from PIL import Image
from . import config


def detect(img: Image.Image, paras: list, min_area_frac: float = 0.02) -> list[list[int]]:
    gray = np.array(img.convert("L"))
    h, w = gray.shape
    ink = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                cv2.THRESH_BINARY_INV, 41, 15)
    for p in paras:                      # erase trusted text
        for ln in p.lines:
            for wd in ln.words:
                if wd.conf >= config.LOW_CONF:
                    pad = 3
                    ink[max(0, wd.y - pad):wd.y + wd.h + pad, max(0, wd.x - pad):wd.x + wd.w + pad] = 0
    k = max(15, int(min(h, w) * 0.012))
    closed = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    closed = cv2.dilate(closed, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    cnts, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for c in cnts:
        x, y, bw, bh = cv2.boundingRect(c)
        area = bw * bh
        if area < min_area_frac * w * h or area > 0.7 * w * h or bw < 60 or bh < 60:
            continue
        density = cv2.countNonZero(ink[y:y + bh, x:x + bw]) / float(area)
        if density < 0.004:
            continue
        boxes.append([x, y, x + bw, y + bh])
    return sorted(boxes, key=lambda b: (b[1], b[0]))


def inside(box, wd) -> bool:
    cx, cy = wd.x + wd.w / 2, wd.y + wd.h / 2
    return box[0] <= cx <= box[2] and box[1] <= cy <= box[3]
