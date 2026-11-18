"""
Read one bill from a screenshot: OCR the calibrated regions, parse and validate.

Two calibration modes are supported:
  - "header": one box around the whole Code / Name / Net / InvNo block (recommended;
    the printed labels make parsing robust).
  - "fields": a separate box for each of code, net and inv_no.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Optional

from PIL import Image

from . import capture, ocr
from .config import Settings
from .parse import FieldResult, parse_code, parse_invoice, parse_net, split_header_text

FIELDS = ("code", "net", "inv_no")


@dataclass
class Bill:
    code: str = ""
    net: str = ""
    inv_no: str = ""
    name: str = ""
    date: str = ""
    confidence: dict = field(default_factory=dict)   # field → 0–100
    issues: list = field(default_factory=list)       # reasons to review
    notes: list = field(default_factory=list)        # auto-corrections made
    raw: dict = field(default_factory=dict)          # field → raw OCR text
    images: dict = field(default_factory=dict)       # crop name → PIL image (not logged)
    user_modified: bool = False
    agreed: set = field(default_factory=set)         # fields confirmed by a second, independent reading
    problem_fields: set = field(default_factory=set) # fields the clerk should look at

    @property
    def needs_review(self) -> bool:
        return bool(self.issues)

    def values(self) -> dict:
        return {"code": self.code, "net": self.net, "inv_no": self.inv_no, "name": self.name,
                "date": self.date}


_LABEL_WORD = re.compile(r"^(code|name|net|amount|invno|inv|no)?[:;.]*$", re.IGNORECASE)


def _value_confidence(words: list[tuple[str, float]]) -> float:
    """Confidence of the value part of a 'Label : value' line (label words ignored)."""
    i = 0
    while i < len(words) and _LABEL_WORD.match(words[i][0]):
        i += 1
    value_words = words[i:] or words
    return min(c for _, c in value_words) if value_words else 0.0


def _limit(key: str, settings: Settings) -> float:
    return settings.amount_confidence_threshold if key == "net" else settings.confidence_threshold


def _parse_one(key: str, text: str, settings: Settings, party_codes) -> FieldResult:
    if key == "code":
        return parse_code(text, party_codes)
    if key == "net":
        return parse_net(text, settings.max_amount, settings.require_decimals)
    return parse_invoice(text, settings.invoice_prefix, settings.invoice_digits)


def _second_settings(settings: Settings) -> Settings:
    """Different image clean-up for an independent second reading."""
    return replace(settings, binarize=not settings.binarize)


def _field_confidence(key: str, result: "ocr.OcrResult") -> float:
    if key == "code":
        # "PARTY NAME(AP37)": only the bracketed code matters, not the name words.
        coded = [c for ws in result.lines for w, c in ws if "(" in w or ")" in w]
        if coded:
            return min(coded)
    return result.confidence


def read_bill(frame: Image.Image, calibration: dict, settings: Settings,
              party_codes: Optional[dict] = None) -> Bill:
    """OCR the calibrated regions of a full-screen frame and return a validated Bill."""
    capture.check_screen_matches(frame, calibration)
    regions = calibration["regions"]

    if calibration.get("mode") == "header":
        return read_header_image(capture.crop(frame, regions["header"]), settings, party_codes)

    bill = Bill()
    raw = {}
    for key in FIELDS:
        img = capture.crop(frame, regions[key])
        bill.images[key] = img
        result = ocr.read(img, key, settings)
        raw[key] = result.text
        bill.confidence[key] = _field_confidence(key, result)
        first = _parse_one(key, result.text, settings, party_codes)
        if first.ok and bill.confidence[key] < _limit(key, settings):
            second = ocr.read(img, key, _second_settings(settings))
            if _parse_one(key, second.text, settings, party_codes).value == first.value:
                bill.agreed.add(key)
    bill.raw = dict(raw)
    apply_parse(bill, raw, settings, party_codes)
    check_confidence(bill, settings)
    return bill


def _header_values(result, settings, party_codes) -> dict:
    raw = split_header_text(result.text)
    return {k: _parse_one(k, raw.get(k, ""), settings, party_codes) for k in FIELDS}


def read_header_image(img: Image.Image, settings: Settings,
                      party_codes: Optional[dict] = None) -> Bill:
    """Read a crop of the whole 'Code / Name / Net / InvNo' block."""
    bill = Bill()
    bill.images["header"] = img
    result = ocr.read(img, "header", settings)
    raw = split_header_text(result.text)
    bill.raw = dict(raw, _full=result.text)
    for words in result.lines:
        line = " ".join(w for w, _ in words)
        for key in split_header_text(line):
            bill.confidence.setdefault(key, _value_confidence(words))
    for key in FIELDS:
        bill.confidence.setdefault(key, 0.0)
    bill.name = raw.get("name", "")

    first = _header_values(result, settings, party_codes)
    doubtful = [k for k in FIELDS if first[k].ok and bill.confidence[k] < _limit(k, settings)]
    if doubtful:
        second = _header_values(ocr.read(img, "header", _second_settings(settings)), settings, party_codes)
        bill.agreed.update(k for k in doubtful if second[k].value == first[k].value)

    apply_parse(bill, raw, settings, party_codes)
    check_confidence(bill, settings)
    return bill


def apply_parse(bill: Bill, raw: dict, settings: Settings, party_codes: Optional[dict]) -> None:
    results: dict[str, FieldResult] = {k: _parse_one(k, raw.get(k, ""), settings, party_codes) for k in FIELDS}
    for key, r in results.items():
        setattr(bill, key, r.value)
        bill.issues.extend(r.issues)
        if r.issues:
            bill.problem_fields.add(key)
        bill.notes.extend(r.notes)
    if party_codes and bill.code in party_codes and party_codes[bill.code]:
        bill.name = party_codes[bill.code]


def check_confidence(bill: Bill, settings: Settings) -> None:
    labels = {"code": "Code", "net": "Amount", "inv_no": "Invoice"}
    for key in FIELDS:
        conf = bill.confidence.get(key, 0.0)
        if conf >= _limit(key, settings):
            continue
        if key in bill.agreed:
            bill.notes.append(f"{labels[key]}: low OCR confidence ({conf:.0f}%), confirmed by a second reading")
        else:
            bill.issues.append(f"{labels[key]} was hard to read ({conf:.0f}% confidence)")
            bill.problem_fields.add(key)


def revalidate(values: dict, settings: Settings, party_codes: Optional[dict]) -> tuple[dict, list]:
    """Re-check values typed by the clerk. Returns (clean values, issues that block saving)."""
    code = parse_code(values.get("code", ""), party_codes)
    net = parse_net(values.get("net", ""), settings.max_amount, require_decimals=False)
    inv = parse_invoice(values.get("inv_no", ""), settings.invoice_prefix, settings.invoice_digits)
    blocking = [i for i in code.issues + net.issues + inv.issues
                if "not in the party list" not in i]  # clerk may add a new party
    clean = {"code": code.value, "net": net.value, "inv_no": inv.value, "name": values.get("name", "")}
    if party_codes and clean["code"] in party_codes and party_codes[clean["code"]]:
        clean["name"] = party_codes[clean["code"]]
    return clean, blocking
