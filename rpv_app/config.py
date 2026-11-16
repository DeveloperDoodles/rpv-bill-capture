"""
Settings for the RPV Bill OCR app.

Defaults live here. Anything can be overridden per machine by putting the same
key in `settings.json` in the project folder (see settings.example.json).
"""

from __future__ import annotations

import json
import os
import platform
import shutil
from dataclasses import dataclass, field, fields
from typing import Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SETTINGS_FILE = os.path.join(PROJECT_ROOT, "settings.json")
CALIBRATION_FILE = os.path.join(PROJECT_ROOT, "rpv_regions.json")
CREDENTIALS_DIR = os.path.join(PROJECT_ROOT, "credentials")
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")
PENDING_FILE = os.path.join(LOGS_DIR, "pending_writes.jsonl")


@dataclass
class Settings:
    # ── Google Sheets ────────────────────────────────────────────────────
    spreadsheet_id: str = ""  # set in settings.json (the long ID in the sheet's web address)
    worksheet_name: str = "Bill Entry"
    header_rows: int = 1
    # Which sheet column each value goes into. Set a value to "" to not write it.
    columns: dict = field(default_factory=lambda: {
        "invoice": "A",
        "code": "B",
        "net": "C",
        "name": "",
        "date": "",
        "timestamp": "G",
        "machine": "Q",
    })
    # Columns that must all be empty for a row to count as free (all the columns this app writes).
    empty_row_check: list = field(default_factory=lambda: ["invoice", "code", "net", "timestamp", "machine"])
    # Name written in the machine column. Blank = the Windows computer name.
    # Set it per computer in settings.json, e.g. "Counter 2".
    machine_name: str = ""
    # "auto" = match what is already in the timestamp column; or "time" / "datetime".
    timestamp_format: str = "auto"
    # The sheet keeps bill numbers without the "L" (81678), as numbers.
    sheet_invoice_with_prefix: bool = False
    oauth_client_file: str = os.path.join(CREDENTIALS_DIR, "client_secret.json")
    oauth_token_file: str = ""  # blank = per-user folder (%APPDATA%/RPVBillOCR), never inside the project

    # ── Validation ───────────────────────────────────────────────────────
    invoice_prefix: str = "L"
    invoice_digits: int = 5          # L61371 → 5 digits after the L
    max_amount: float = 100_000_000  # anything above this is treated as a misread
    require_decimals: bool = True    # RPV always shows ".00", so a missing dot = misread
    party_codes_file: str = os.path.join(PROJECT_ROOT, "party_codes.csv")

    # ── OCR ──────────────────────────────────────────────────────────────
    confidence_threshold: float = 80    # below → clerk must check the bill
    amount_confidence_threshold: float = 88  # stricter for money
    upscale_factor: float = 0       # 0 = automatic (recommended), or a fixed factor like 2
    sharpen: bool = True
    binarize: bool = True
    tesseract_path: str = ""  # leave blank to auto-detect

    @property
    def project_root(self) -> str:
        return PROJECT_ROOT


def _find_tesseract(explicit: str = "") -> Optional[str]:
    if explicit and os.path.exists(explicit):
        return explicit
    path = shutil.which("tesseract")
    if path:
        return path
    if platform.system() == "Windows":
        for p in (
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
        ):
            if os.path.exists(p):
                return p
    return None


def load_settings(path: str = SETTINGS_FILE) -> Settings:
    """Load defaults, then apply overrides from settings.json if present."""
    s = Settings()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            overrides = json.load(f)
        known = {f.name for f in fields(Settings)}
        unknown = [k for k in overrides if k not in known and not k.startswith("_")]
        if unknown:
            raise ValueError(f"Unknown setting(s) in {os.path.basename(path)}: {', '.join(unknown)}")
        for key, value in overrides.items():
            if key.startswith("_"):
                continue  # allow "_comment" keys
            if key == "columns":
                merged = dict(s.columns)
                merged.update(value)
                value = merged
            setattr(s, key, value)
    _check_columns(s)
    return s


def _check_columns(s: Settings) -> None:
    import re
    if s.timestamp_format not in ("auto", "time", "datetime"):
        raise ValueError('timestamp_format must be "auto", "time" or "datetime"')
    for name, col in s.columns.items():
        if col and not re.fullmatch(r"[A-Z]{1,2}", str(col)):
            raise ValueError(f"Column for '{name}' must be a letter like 'A' or 'AB', got {col!r}")
    for name in ("invoice", "code", "net"):
        if not s.columns.get(name):
            raise ValueError(f"Column for '{name}' is required in settings.")
    used = [c for c in s.columns.values() if c]
    if len(used) != len(set(used)):
        raise ValueError("Two values are mapped to the same sheet column in settings.")


def tesseract_path(s: Settings) -> Optional[str]:
    return _find_tesseract(s.tesseract_path)


def load_calibration() -> Optional[dict]:
    if os.path.exists(CALIBRATION_FILE):
        with open(CALIBRATION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_calibration(data: dict) -> None:
    with open(CALIBRATION_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_party_codes(s: Settings) -> dict[str, str]:
    """
    Load the list of valid party codes from a CSV with columns: code,name
    (a header row is optional). Returns {} if the file doesn't exist.
    """
    import csv
    path = s.party_codes_file
    if not path or not os.path.exists(path):
        return {}
    codes: dict[str, str] = {}
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            if not row or not row[0].strip():
                continue
            code = row[0].strip().upper()
            if code in ("CODE", "PARTY CODE", "PARTY_CODE"):
                continue  # header row
            codes[code] = row[1].strip() if len(row) > 1 else ""
    return codes
