"""
Step 2 – OCR with Tesseract.
Returns raw text, mean confidence, fallback flag, and page count.
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from pathlib import Path

import pytesseract
from pdf2image import convert_from_bytes
from PIL import Image

log = logging.getLogger(__name__)

# Minimum alphanumeric chars before we trust the result
_MIN_ALNUM = 40
# Below this confidence we use the fallback flag
_MIN_CONFIDENCE = 60.0


@dataclass
class OcrResult:
    text: str
    mean_confidence: float | None
    page_count: int
    used_fallback: bool
    error: str | None = None
    word_boxes: list[dict] = field(default_factory=list)  # for PII redaction on image path


def _alnum_count(text: str) -> int:
    return sum(1 for c in text if c.isalnum())


def _ocr_image(img: Image.Image) -> tuple[str, float | None, list[dict]]:
    """Run tesseract on a PIL image, return (text, confidence, word_boxes)."""
    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

    words, confs = [], []
    boxes = []
    for i, word in enumerate(data["text"]):
        conf = data["conf"][i]
        if isinstance(conf, str):
            try:
                conf = int(conf)
            except ValueError:
                conf = -1
        if conf < 0:
            continue
        if word.strip():
            words.append(word)
            confs.append(conf)
            boxes.append({
                "word": word,
                "left": data["left"][i],
                "top": data["top"][i],
                "width": data["width"][i],
                "height": data["height"][i],
                "conf": conf,
            })

    text = " ".join(words)
    mean_conf = (sum(confs) / len(confs)) if confs else None
    return text, mean_conf, boxes


def ocr_file(file_bytes: bytes, mime: str) -> OcrResult:
    """
    Run OCR on the file.
    mime must be image/png, image/jpeg, or application/pdf.
    """
    images: list[Image.Image] = []

    if mime == "application/pdf":
        try:
            pil_pages = convert_from_bytes(file_bytes, dpi=200)
            images.extend(pil_pages)
        except Exception as exc:
            log.warning("pdf_conversion_error class=%s", type(exc).__name__)
            return OcrResult(
                text="", mean_confidence=None, page_count=0,
                used_fallback=True, error="pdf_conversion_error",
            )
    else:
        try:
            img = Image.open(io.BytesIO(file_bytes)).convert("RGB")
            images.append(img)
        except Exception as exc:
            log.warning("image_open_error class=%s", type(exc).__name__)
            return OcrResult(
                text="", mean_confidence=None, page_count=0,
                used_fallback=True, error="image_open_error",
            )

    all_text_parts: list[str] = []
    all_confs: list[float] = []
    all_boxes: list[dict] = []
    fallback = False

    for img in images:
        text, conf, boxes = _ocr_image(img)
        all_text_parts.append(text)
        all_boxes.extend(boxes)
        if conf is not None:
            all_confs.append(conf)

    combined = "\n".join(all_text_parts).strip()
    mean_conf = (sum(all_confs) / len(all_confs)) if all_confs else None

    # Fallback flag: too short or low confidence
    if _alnum_count(combined) < _MIN_ALNUM:
        fallback = True
        log.warning("ocr_fallback_triggered reason=alnum_too_low count=%d", _alnum_count(combined))
    elif mean_conf is not None and mean_conf < _MIN_CONFIDENCE:
        fallback = True
        log.warning("ocr_fallback_triggered reason=low_confidence conf=%.1f", mean_conf)

    return OcrResult(
        text=combined,
        mean_confidence=mean_conf,
        page_count=len(images),
        used_fallback=fallback,
        word_boxes=all_boxes,
    )
