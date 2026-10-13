"""Central configuration. Everything is overridable via environment variables."""
import os
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", "./data")).resolve()
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "300"))
LOW_CONF = float(os.getenv("LOW_CONF_THRESHOLD", "0.60"))   # words/blocks below this go to review
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "7"))
JOB_WORKERS = int(os.getenv("JOB_WORKERS", "2"))             # concurrent jobs
PAGE_WORKERS = int(os.getenv("PAGE_WORKERS", "2"))           # concurrent pages per job
TESS_LANG = os.getenv("TESS_LANG", "eng")
TESS_TIMEOUT = int(os.getenv("TESS_TIMEOUT", "120"))
LATEX_TIMEOUT = int(os.getenv("LATEX_TIMEOUT", "300"))

# Optional AI-assisted transcription of *uncertain* regions (suggestions only, never auto-applied).
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
VISION_MODEL = os.getenv("VISION_MODEL", "claude-sonnet-5-5")

QUALITY = {
    "standard": {"dpi": 200, "deskew": False, "vision": False},
    "advanced": {"dpi": 300, "deskew": True, "vision": True},
    "high":     {"dpi": 400, "deskew": True, "vision": True},
}
PAGE_SIZES = {"a4": "a4paper", "letter": "letterpaper", "a5": "a5paper"}
FONTS = {  # key -> fontspec family; filtered at runtime by what fc-list reports
    "serif": "Latin Modern Roman",
    "sans": "Latin Modern Sans",
    "times": "TeX Gyre Termes",
    "dejavu": "DejaVu Serif",
}
FONT_SIZES = (10, 11, 12)
MODES = ("textbook", "pyq")
