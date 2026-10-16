"""Read a document: what kind it is, its text (OCR for scans and photos), page count, preview.

PDF text comes from pypdf. A PDF with (almost) no text is a scan, so its first pages are
rendered with pdfium and read with OCR. Photos of documents are read with OCR directly.
"""

import io
import logging
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from ..config import get_settings

log = logging.getLogger(__name__)

PREVIEW_WIDTH = 700
MIN_CHARS_PER_PAGE = 40  # less than this on average = scanned PDF


class NotADocument(ValueError):
    pass


@dataclass
class ReadResult:
    kind: str                 # pdf | image
    mime: str
    ext: str
    pages: int
    text: str
    text_source: str | None   # pdf | ocr | None
    preview_jpeg: bytes | None


def detect(data: bytes) -> tuple[str, str, str]:
    """(kind, mime, ext). Raises NotADocument for anything else."""
    if data[:5] == b"%PDF-" or b"%PDF-" in data[:1024]:
        return "pdf", "application/pdf", "pdf"
    if data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"mif1", b"msf1"):
        raise NotADocument("HEIC photos aren't supported. In the Shortcut, add 'Convert Image' to JPEG first.")
    try:
        img = Image.open(io.BytesIO(data))
        fmt = (img.format or "").upper()
    except (UnidentifiedImageError, OSError) as e:
        raise NotADocument("Only PDFs and photos (JPG, PNG, WEBP) can be saved.") from e
    mime = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp", "GIF": "image/gif",
            "BMP": "image/bmp", "TIFF": "image/tiff"}.get(fmt, "image/png")
    return "image", mime, {"JPEG": "jpg"}.get(fmt, fmt.lower() or "png")


def _jpeg(img: Image.Image, width: int = PREVIEW_WIDTH) -> bytes:
    img = ImageOps.exif_transpose(img).convert("RGB")
    if img.width > width:
        img = img.resize((width, round(img.height * width / img.width)))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=82)
    return buf.getvalue()


# ---------------------------------------------------------------- OCR

_ocr = None


def ocr_image(img: Image.Image) -> str:
    """Text from an image, in reading order (lines top to bottom)."""
    global _ocr
    if not get_settings().ocr_enabled:
        return ""
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return ""
    if _ocr is None:
        _ocr = RapidOCR()
    buf = io.BytesIO()
    ImageOps.exif_transpose(img).convert("RGB").save(buf, "PNG")
    try:
        result, _ = _ocr(buf.getvalue())
    except Exception as e:
        log.info("OCR failed: %s", e)
        return ""
    if not result:
        return ""
    line_height = max(12, sorted(abs(r[0][2][1] - r[0][0][1]) for r in result)[len(result) // 2] * 0.6)
    rows = sorted(result, key=lambda r: (round(r[0][0][1] / line_height), r[0][0][0]))
    lines, last = [], None
    for box, text, _score in rows:
        y = round(box[0][1] / line_height)
        if lines and y == last:
            lines[-1] += " " + text
        else:
            lines.append(text)
        last = y
    return "\n".join(lines).strip()


# ---------------------------------------------------------------- PDF

def _read_pdf(data: bytes) -> tuple[int, str, str | None, bytes | None]:
    s = get_settings()
    import pypdf

    text_parts: list[str] = []
    pages = 0
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            reader.decrypt("")  # many "protected" PDFs open with an empty password
        pages = len(reader.pages)
        for page in reader.pages[: s.text_max_pages]:
            try:
                text_parts.append(page.extract_text() or "")
            except Exception:
                text_parts.append("")
    except Exception as e:
        log.info("pypdf couldn't read the PDF: %s", e)

    text = "\n\n".join(t.strip() for t in text_parts if t.strip())
    source = "pdf" if text else None
    preview = None
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(data)
        pages = pages or len(pdf)
        first = pdf[0].render(scale=1.5).to_pil()
        preview = _jpeg(first)
        if len(text) < MIN_CHARS_PER_PAGE * max(1, min(pages, s.ocr_max_pages)):
            # A scan: read the first pages with OCR.
            ocr_parts = [ocr_image(first)]
            for i in range(1, min(len(pdf), s.ocr_max_pages)):
                ocr_parts.append(ocr_image(pdf[i].render(scale=2).to_pil()))
            ocr_text = "\n\n".join(p for p in ocr_parts if p)
            if len(ocr_text) > len(text):
                text, source = ocr_text, "ocr"
    except Exception as e:  # pdfium missing or blocked, or a damaged PDF: keep what pypdf found
        log.info("PDF render/OCR skipped: %s", e)
    return pages, text, source, preview


def read(data: bytes) -> ReadResult:
    kind, mime, ext = detect(data)
    if kind == "pdf":
        pages, text, source, preview = _read_pdf(data)
        return ReadResult(kind, mime, ext, pages, text, source, preview)
    img = Image.open(io.BytesIO(data))
    text = ocr_image(img)
    return ReadResult(kind, mime, ext, 1, text, "ocr" if text else None, _jpeg(img))
