"""Image analysis tools — drag/drop an image and get a description.

Supports:
  - LLM vision (uses the configured API provider to describe images)
  - OCR fallback (pytesseract, if available)

Uses the same OpenAI-compatible client as the rest of the app, so any
vision-capable model at the configured provider will work.
"""

import base64
import io
from pathlib import Path
from typing import Optional

from PIL import Image as PILImage

from .registry import Tool


# ── helpers ────────────────────────────────────────────────────────────────

def _encode_image(path: str) -> str:
    """Load an image and return a base64 data-URI for the vision API."""
    img = PILImage.open(path)
    # Convert RGBA / P to RGB so JPEG-encoding works
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}"


def _ocr_text(path: str) -> Optional[str]:
    """Try OCR via pytesseract.  Returns None if not installed."""
    try:
        import pytesseract
        img = PILImage.open(path)
        text = pytesseract.image_to_string(img)
        return text.strip() or None
    except ImportError:
        return None


def _call_vision(image_path: str, prompt: str) -> str:
    """Call the configured LLM with a vision request."""
    from ..config import Config

    cfg = Config()

    # Build an OpenAI-compatible client
    from openai import OpenAI
    client = OpenAI(
        base_url=cfg.base_url,
        api_key=cfg.api_key,
        timeout=30,
    )

    data_uri = _encode_image(image_path)
    response = client.chat.completions.create(
        model=cfg.model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_uri}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        max_tokens=1024,
        temperature=0.3,
    )
    return response.choices[0].message.content.strip()


# ── tool ───────────────────────────────────────────────────────────────────

class ImageAnalyzeTool(Tool):
    name = "ImageAnalyze"
    description = (
        "Analyze an image by path and return a detailed description. "
        "Use this when the user drags or references an image file. "
        "Supports JPEG, PNG, GIF, BMP, WebP. "
        "Returns a natural-language description of what's in the image."
    )
    permission_risk = "safe"
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute path to the image file to analyze",
            },
            "question": {
                "type": "string",
                "description": (
                    "Optional specific question about the image "
                    "(e.g. 'What text is in this screenshot?', "
                    "'What color is the car?'). "
                    "If omitted, a general description is returned."
                ),
            },
        },
        "required": ["file_path"],
    }

    def run(self, file_path: str, question: str = "") -> str:
        path = Path(file_path)
        if not path.exists():
            return f"Error: image file not found: {file_path}"

        # Build the prompt
        if question.strip():
            prompt = (
                f"The user uploaded this image and asks: {question.strip()} "
                "Answer concisely and directly. If the image contains text, "
                "transcribe relevant parts."
            )
        else:
            prompt = (
                "Describe this image in detail. Cover what objects/people are "
                "visible, colors, text (transcribe any text you see), layout, "
                "and the overall scene. Be concise but thorough."
            )

        # Try vision API first
        try:
            description = _call_vision(str(path), prompt)
            # Also try OCR as a supplement
            ocr = _ocr_text(str(path))
            if ocr and ocr not in description:
                description += f"\n\n[OCR extracted text]:\n{ocr}"
            return description
        except Exception as e:
            # Vision failed — fall back to OCR-only
            ocr = _ocr_text(str(path))
            if ocr:
                return f"[Vision API unavailable — OCR fallback]\n\n{ocr}"
            # Also try basic metadata
            try:
                img = PILImage.open(path)
                meta = f"Format: {img.format}, Size: {img.size}, Mode: {img.mode}"
                return f"Error: unable to analyze image ({e}).  Basic info: {meta}"
            except Exception:
                return f"Error: unable to analyze image ({e})"
