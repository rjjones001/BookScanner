"""Stage 5: IR -> LaTeX -> PDF with XeLaTeX. Real typesetting, real text layer."""
from __future__ import annotations
import os
import re
import subprocess
from pathlib import Path
from . import config
from .ir import Doc

SPECIALS = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
            "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
UNSAFE = re.compile(r"\\(input|include|write|read|openin|openout|immediate|catcode|csname|def|edef|gdef|let|"
                    r"newcommand|renewcommand|usepackage|href|url|special|pdf\w*|directlua|ShellEscape|verb)\b", re.I)


def esc(s: str) -> str:
    return "".join(SPECIALS.get(c, c) for c in s)


def safe_math(latex: str) -> bool:
    return bool(latex.strip()) and not UNSAFE.search(latex) and latex.count("{") == latex.count("}")


def installed_fonts() -> dict[str, str]:
    try:
        out = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True, timeout=20).stdout
    except Exception:
        out = ""
    have = {f.strip() for line in out.splitlines() for f in line.split(",")}
    return {k: v for k, v in config.FONTS.items() if v in have} or {"serif": "Latin Modern Roman"}


PREAMBLE = r"""\documentclass[%(size)dpt]{article}
\usepackage[%(paper)s,margin=25mm]{geometry}
\usepackage{fontspec}
\setmainfont{%(font)s}[Ligatures=NoCommon]
\usepackage{amsmath,amssymb,graphicx,fancyhdr,needspace,setspace}
\hyphenpenalty=10000 \exhyphenpenalty=10000 \sloppy \emergencystretch=3em
\setstretch{1.15}
\setlength{\parindent}{0pt}\setlength{\parskip}{0.6em}
\pagestyle{fancy}\fancyhf{}\fancyfoot[C]{\thepage}\fancyhead[C]{\small %(title)s}
\renewcommand{\headrulewidth}{0.3pt}
\begin{document}
"""


def to_latex(doc: Doc, root: Path, page_size="a4", font="serif", size=11,
             header=True, q_gap_pt=8, equations_as_math=True) -> tuple[str, list[str]]:
    warns: list[str] = []
    fonts = installed_fonts()
    fam = fonts.get(font) or next(iter(fonts.values()))
    if font not in fonts:
        warns.append(f"Font \x27{font}\x27 not installed; used {fam}")
    out = [PREAMBLE % dict(size=size, paper=config.PAGE_SIZES.get(page_size, "a4paper"),
                           font=fam, title=esc(doc.title) if header else "")]
    for pg in doc.pages:
        out.append(f"% ---- source page {pg.number}")
        blocks = pg.blocks
        for i, b in enumerate(blocks):
            nxt = blocks[i + 1].kind if i + 1 < len(blocks) else ""
            out.append(f"% block {b.id}")
            if b.kind == "heading":
                cmd = "section*" if b.level == 1 else "subsection*"
                out.append(rf"\needspace{{5\baselineskip}}\{cmd}{{{esc(b.text)}}}")
            elif b.kind == "question":
                out.append(rf"\vspace{{{q_gap_pt}pt}}\needspace{{6\baselineskip}}\par\hangindent=2.2em\hangafter=1"
                           rf"\noindent\textbf{{{esc(b.label)}}}\ {esc(b.text)}" + (r"\nopagebreak[4]" if nxt == "option" else ""))
            elif b.kind == "option":
                out.append(rf"\par\hangindent=4.2em\hangafter=1\hspace{{2.2em}}\textbf{{{esc(b.label)}}}\ {esc(b.text)}"
                           + (r"\nopagebreak[4]" if nxt == "option" else ""))
            elif b.kind == "list_item":
                out.append(rf"\par\hangindent=2em\hangafter=1\hspace{{0.5em}}{esc(b.label)}\ {esc(b.text)}")
            elif b.kind == "equation":
                if equations_as_math and safe_math(b.latex):
                    out.append(rf"\begin{{equation*}}{b.latex}\end{{equation*}}")
                else:
                    warns.append(f"Equation {b.id} had missing/unsafe LaTeX; printed as verbatim text")
                    out.append(rf"\par\texttt{{{esc(b.latex or b.text)}}}")
            elif b.kind == "figure":
                p = (root / b.image).resolve()
                out.append(rf"\needspace{{12\baselineskip}}\begin{{center}}\includegraphics[width=\linewidth,"
                           rf"height=0.5\textheight,keepaspectratio]{{{p.as_posix()}}}\end{{center}}")
            else:
                out.append(rf"\par {esc(b.text)}")
    out.append(r"\end{document}")
    return "\n".join(out), warns


def compile_pdf(tex: str, workdir: Path, name="output") -> tuple[Path, str]:
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / f"{name}.tex").write_text(tex, encoding="utf-8")
    env = dict(os.environ, openout_any="p", openin_any="p")     # restrict file access
    p = subprocess.run(["xelatex", "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape",
                        f"{name}.tex"], cwd=workdir, capture_output=True, text=True,
                       timeout=config.LATEX_TIMEOUT, env=env)
    log = (workdir / f"{name}.log").read_text(errors="replace") if (workdir / f"{name}.log").exists() else p.stdout
    pdf = workdir / f"{name}.pdf"
    if p.returncode != 0 or not pdf.exists():
        raise RuntimeError("LaTeX compilation failed: " + "\n".join(
            l for l in log.splitlines() if l.startswith("!") or l.startswith("l."))[:600])
    return pdf, log


def to_markdown(doc: Doc) -> str:
    lines = []
    for pg in doc.pages:
        for b in pg.blocks:
            if b.kind == "heading":
                lines.append(("#" if b.level == 1 else "##") + " " + b.text)
            elif b.kind == "question":
                lines.append(f"**{b.label}** {b.text}")
            elif b.kind == "option":
                lines.append(f"- {b.label} {b.text}")
            elif b.kind == "list_item":
                lines.append(f"- {b.text}")
            elif b.kind == "equation":
                lines.append(f"$$\n{b.latex}\n$$")
            elif b.kind == "figure":
                lines.append(f"*[Figure preserved as image, source page {pg.number}]*")
            else:
                lines.append(b.text)
        lines.append("")
    return "\n\n".join(lines)
