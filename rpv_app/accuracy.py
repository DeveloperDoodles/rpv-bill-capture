"""
Accuracy check: run the real OCR + parsing on saved header crops and compare
with the correct values.

Folder layout:  <folder>/ground_truth.csv  with columns  file,code,net,inv_no
                <folder>/<file>             each a crop of the bill header block

A bill counts as SAFE if it is either read fully correctly, or flagged for the
clerk to review. A bill that is wrong AND not flagged is a SILENT ERROR — the
number that must stay at zero.
"""

from __future__ import annotations

import csv
import os

from PIL import Image

from . import ocr
from .bill import FIELDS, read_header_image
from .config import Settings, load_party_codes


def run(folder: str, settings: Settings) -> int:
    ocr.setup_tesseract(settings)
    party_codes = load_party_codes(settings)
    truth_path = os.path.join(folder, "ground_truth.csv")
    with open(truth_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    correct = flagged = silent = 0
    field_ok = {k: 0 for k in FIELDS}
    for row in rows:
        img = Image.open(os.path.join(folder, row["file"])).convert("RGB")
        bill = read_header_image(img, settings, party_codes)
        got = bill.values()
        wrong = [k for k in FIELDS if got[k] != row[k]]
        for k in FIELDS:
            field_ok[k] += got[k] == row[k]
        if not wrong:
            status = "OK      " if not bill.needs_review else "OK*     "
            correct += 1
        elif bill.needs_review:
            status = "FLAGGED "
            flagged += 1
        else:
            status = "SILENT!!"
            silent += 1
        conf = " ".join(f"{k}={bill.confidence.get(k, 0):.0f}" for k in FIELDS)
        print(f"{status} {row['file']:30s} {got['code']:6s} {got['net']:>11s} {got['inv_no']:8s}  [{conf}]")
        if wrong:
            print(f"         expected {row['code']} {row['net']} {row['inv_no']}; issues: {bill.issues}")
        elif bill.needs_review:
            print(f"         (correct, but flagged: {bill.issues})")

    n = len(rows)
    print("-" * 70)
    print(f"Bills: {n}   correct: {correct}   wrong-but-flagged: {flagged}   SILENT ERRORS: {silent}")
    print("Per field: " + ", ".join(f"{k} {field_ok[k]}/{n}" for k in FIELDS))
    print("(OK* = correct but sent to the clerk anyway)")
    return 1 if silent else 0
