"""Optional AI-assisted transcription of uncertain crops (Anthropic API). Results are stored as
`suggestion` and shown beside the original crop; they are NEVER applied automatically.
UNTESTED in CI: requires ANTHROPIC_API_KEY and sends image crops to Anthropic."""
from __future__ import annotations
import base64
import io
import httpx
from PIL import Image
from . import config

PROMPT = ("Transcribe exactly the text in this image crop from a scanned document. Do not correct, "
          "summarise or add anything. Write maths as LaTeX inside $...$. Mark anything illegible as [illegible]. "
          "Output only the transcription.")


def enabled() -> bool:
    return bool(config.ANTHROPIC_API_KEY)


def transcribe(crop: Image.Image) -> str:
    buf = io.BytesIO()
    crop.convert("RGB").save(buf, "PNG")
    r = httpx.post("https://api.anthropic.com/v1/messages", timeout=60, headers={
        "x-api-key": config.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"},
        json={"model": config.VISION_MODEL, "max_tokens": 600, "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                         "data": base64.b64encode(buf.getvalue()).decode()}},
            {"type": "text", "text": PROMPT}]}]})
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json().get("content", [])).strip()
