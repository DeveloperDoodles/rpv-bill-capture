"""
Image clean-up and Tesseract OCR.

Uses only Pillow (no OpenCV / numpy), which keeps the Windows install small.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PIL import Image, ImageFilter, ImageOps

from .config import Settings, tesseract_path

# Tesseract options per field. --psm 7 = a single line of text.
FIELD_TESS_CONFIG = {
    # No whitelist: the box may hold the whole "PARTY NAME(AP37)" line and the brackets matter.
    "code": "--psm 7",
    "net": "--psm 7 -c tessedit_char_whitelist=0123456789.,",
    "inv_no": "--psm 7 -c tessedit_char_whitelist=L0123456789",
    "header": "--psm 6",  # a block of several lines
}


class TesseractMissing(RuntimeError):
    pass


@dataclass
class OcrResult:
    text: str
    confidence: float  # lowest word confidence, 0–100
    image: Image.Image  # the crop that was read (before clean-up), for the log / review window
    lines: list = field(default_factory=list)  # [[(word, confidence), ...], ...] per text line


def setup_tesseract(settings: Settings) -> str:
    import pytesseract
    path = tesseract_path(settings)
    if not path:
        raise TesseractMissing(
            "Tesseract OCR is not installed or could not be found.\n"
            "Install it to C:\\Program Files\\Tesseract-OCR\\ (see README), "
            "or set \"tesseract_path\" in settings.json."
        )
    pytesseract.pytesseract.tesseract_cmd = path
    return path


def _otsu_threshold(gray: Image.Image) -> int:
    hist = gray.histogram()
    total = sum(hist)
    sum_all = sum(i * h for i, h in enumerate(hist))
    sum_bg = weight_bg = 0
    best_t, best_var = 0, -1.0
    for t in range(256):
        weight_bg += hist[t]
        if weight_bg == 0:
            continue
        weight_fg = total - weight_bg
        if weight_fg == 0:
            break
        sum_bg += t * hist[t]
        mean_bg = sum_bg / weight_bg
        mean_fg = (sum_all - sum_bg) / weight_fg
        var = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
        if var > best_var:
            best_var, best_t = var, t
    return best_t


def preprocess(img: Image.Image, settings: Settings) -> Image.Image:
    """Grayscale → upscale → sharpen → black/white. Dark-on-light output."""
    gray = ImageOps.grayscale(img)
    # Light text on a dark background reads badly; flip it.
    if _mean(gray) < 110:
        gray = ImageOps.invert(gray)
    f = float(settings.upscale_factor) if settings.upscale_factor else auto_scale(gray)
    if f > 1:
        gray = gray.resize((round(gray.width * f), round(gray.height * f)), Image.BICUBIC)
    if settings.sharpen:
        gray = gray.filter(ImageFilter.UnsharpMask(radius=3, percent=150, threshold=0))
    if settings.binarize:
        t = _otsu_threshold(gray)
        gray = gray.point(lambda p: 255 if p > t else 0)
    # A white border helps Tesseract with text touching the crop edge.
    return ImageOps.expand(gray, border=round(10 * max(f, 1)), fill=255)


TARGET_LINE_HEIGHT = 54  # px; tuned on real RPV crops (27px text → 2× scored best)


def text_line_height(gray: Image.Image) -> float:
    """Median height (px) of the rows of text in a dark-on-light image."""
    t = _otsu_threshold(gray)
    w, h = gray.size
    px = gray.point(lambda p: 1 if p <= t else 0).load()
    min_dark = max(1, w // 200)
    runs, run = [], 0
    for y in range(h):
        dark = sum(px[x, y] for x in range(0, w, 2)) >= min_dark
        if dark:
            run += 1
        elif run:
            runs.append(run)
            run = 0
    if run:
        runs.append(run)
    runs = [r for r in runs if r >= 4]  # ignore separator lines / specks
    if not runs:
        return 0.0
    runs.sort()
    return float(runs[len(runs) // 2])


def auto_scale(gray: Image.Image) -> float:
    """Upscale factor that brings the text to TARGET_LINE_HEIGHT (between 1× and 4×)."""
    h = text_line_height(gray)
    if h <= 0:
        return 2.0
    return max(1.0, min(4.0, round(TARGET_LINE_HEIGHT / h, 1)))


def _mean(gray: Image.Image) -> float:
    hist = gray.histogram()
    n = sum(hist) or 1
    return sum(i * h for i, h in enumerate(hist)) / n


def read(img: Image.Image, kind: str, settings: Settings) -> OcrResult:
    """OCR one crop. `kind` is 'code', 'net', 'inv_no' or 'header'."""
    import pytesseract

    processed = preprocess(img, settings)
    data = pytesseract.image_to_data(
        processed,
        config=FIELD_TESS_CONFIG.get(kind, "--psm 7"),
        output_type=pytesseract.Output.DICT,
    )

    grouped: dict[tuple, list[tuple[str, float]]] = {}
    for i, word in enumerate(data["text"]):
        word = (word or "").strip()
        conf = float(data["conf"][i])
        if not word or conf < 0:  # -1 = layout box, not a word
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        grouped.setdefault(key, []).append((word, conf))

    lines = [ws for _, ws in sorted(grouped.items())]
    text = "\n".join(" ".join(w for w, _ in ws) for ws in lines)
    confs = [c for ws in lines for _, c in ws]
    confidence = min(confs) if confs else 0.0
    return OcrResult(text=text, confidence=confidence, image=img, lines=lines)
