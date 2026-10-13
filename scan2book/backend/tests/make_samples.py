"""Generates synthetic *image-only* PDFs (no text layer) so tests exercise the real OCR path."""
import io
import pymupdf
from PIL import Image, ImageDraw, ImageFont

W, H = 1654, 2339   # A4 @ 200 dpi
FD = "/usr/share/fonts/truetype/dejavu/"


def font(size, bold=False):
    return ImageFont.truetype(FD + ("DejaVuSerif-Bold.ttf" if bold else "DejaVuSerif.ttf"), size)


def textbook_page():
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    d.text((150, 150), "Chapter One Motion", font=font(78, True), fill="black")
    y = 380
    paras = [
        ["Motion is the change in position of an object with respect to time.",
         "Velocity describes both the speed and the direction of that motion."],
        ["Acceleration is the rate at which velocity changes over a given interval.",
         "A body moving with constant velocity has zero acceleration."],
    ]
    for p in paras:
        for line in p:
            d.text((150, y), line, font=font(38), fill="black")
            y += 62
        y += 50
    text = [w for p in paras for l in p for w in l.split()]
    return im, ["Chapter", "One", "Motion"] + text


def pyq_page():
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    y = 200
    qs = [("1.", "What is the SI unit of force in physics?", ["Newton", "Joule", "Watt", "Pascal"]),
          ("2.", "Which quantity is a vector among the following?", ["Mass", "Velocity", "Energy", "Time"])]
    for num, q, opts in qs:
        d.text((150, y), f"{num} {q}", font=font(38), fill="black")
        y += 70
        for lab, o in zip("ABCD", opts):
            d.text((230, y), f"({lab}) {o}", font=font(38), fill="black")
            y += 60
        y += 60
    return im


def figure_page():
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    d.text((150, 150), "Consider the triangle shown below in the diagram.", font=font(38), fill="black")
    d.polygon([(400, 1100), (900, 1100), (650, 500)], outline="black", width=6)
    d.ellipse([950, 600, 1350, 1000], outline="black", width=6)
    d.line([(400, 1300), (1300, 1300)], fill="black", width=5)
    d.line([(850, 1150), (850, 1450)], fill="black", width=5)
    d.text((150, 1650), "The figure above shows a triangle and a circle.", font=font(38), fill="black")
    return im


def to_pdf(images, path):
    doc = pymupdf.open()
    for im in images:
        buf = io.BytesIO()
        im.save(buf, "PNG")
        page = doc.new_page(width=im.width * 72 / 200, height=im.height * 72 / 200)
        page.insert_image(page.rect, stream=buf.getvalue())
    doc.save(path)
    return path
