"""
Turn raw OCR text into clean, validated bill values.

Everything here is pure (no screen, no network) so it can be unit tested.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Optional

# Characters Tesseract commonly confuses with digits.
_DIGIT_FIXES = str.maketrans({
    "O": "0", "o": "0", "Q": "0", "D": "0",
    "I": "1", "l": "1", "|": "1", "i": "1", "!": "1",
    "S": "5", "s": "5",
    "B": "8",
    "Z": "2", "z": "2",
    "G": "6",
})


@dataclass
class FieldResult:
    value: str = ""
    raw: str = ""
    issues: list = field(default_factory=list)  # reasons the clerk must look at it
    notes: list = field(default_factory=list)   # harmless auto-corrections, for the log

    @property
    def ok(self) -> bool:
        return not self.issues


def _strip_label(text: str, label_pattern: str) -> str:
    """Remove a leading 'Label :' if the OCR picked it up."""
    return re.sub(rf"^\s*{label_pattern}\s*[:;.]?\s*", "", text, flags=re.IGNORECASE).strip()


# ─── Code ────────────────────────────────────────────────────────────────────

def parse_code(text: str, party_codes: Optional[dict] = None) -> FieldResult:
    r = FieldResult(raw=text)
    value = _strip_label(text.strip(), r"code")
    bracket = re.search(r"\(([A-Za-z0-9 ]{1,12})\)?\s*$", value)
    if bracket:  # new RPV layout: "PARTY NAME(AP37)"
        value = bracket.group(1)
    value = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    r.value = value

    if not value:
        r.issues.append("Code is empty")
        return r
    if not re.fullmatch(r"[A-Z][A-Z0-9]{0,9}", value):
        r.issues.append(f"Code '{value}' doesn't look like a party code")
        return r

    if party_codes:
        if value not in party_codes:
            suggestion = closest_code(value, party_codes)
            if suggestion:
                r.issues.append(f"Code '{value}' is not in the party list — did you mean '{suggestion}'?")
            else:
                r.issues.append(f"Code '{value}' is not in the party list")
    return r


def closest_code(value: str, party_codes: dict) -> Optional[str]:
    """Return the single party code one edit away from `value`, if exactly one exists."""
    matches = [c for c in party_codes if _edit_distance(value, c) == 1]
    return matches[0] if len(matches) == 1 else None


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


# ─── Net amount ──────────────────────────────────────────────────────────────

def parse_net(text: str, max_amount: float = 1e8, require_decimals: bool = True) -> FieldResult:
    r = FieldResult(raw=text)
    value = _strip_label(text.strip(), r"net(\s*amount)?")
    value = value.replace(" ", "")
    fixed = value.translate(_DIGIT_FIXES)
    if fixed != value:
        r.notes.append(f"Fixed look-alike characters: '{value}' → '{fixed}'")
        r.issues.append("Amount had letters that look like digits — please check")
    value = fixed

    m = re.search(r"\d[\d,]*(?:\.\d+)?", value)
    if not m:
        r.issues.append("No amount found — if this bill has more pages, go to its LAST page")
        r.value = ""
        return r
    number = m.group(0)
    leftover = (value[:m.start()] + value[m.end():]).strip(" .,:;")
    if leftover:
        r.issues.append(f"Unexpected text around amount: '{leftover}'")

    number = number.replace(",", "")
    if require_decimals and "." not in number:
        r.issues.append("Amount has no decimal point — the dot may have been misread")
    if "." in number and len(number.split(".")[1]) != 2:
        r.issues.append("Amount should have exactly 2 decimal places")

    try:
        amount = Decimal(number)
    except InvalidOperation:
        r.issues.append(f"'{number}' is not a valid amount")
        r.value = number
        return r

    if amount <= 0:
        r.issues.append("Amount is zero")
    elif amount > Decimal(str(max_amount)):
        r.issues.append(f"Amount {amount} is unusually large")

    r.value = f"{amount:.2f}"
    return r


# ─── Invoice number ──────────────────────────────────────────────────────────

def parse_invoice(text: str, prefix: str = "L", digits: int = 5) -> FieldResult:
    """
    Expect `prefix` followed by exactly `digits` digits (e.g. L61371).

    Known OCR errors handled safely because the length is fixed:
      "161371" (L read as 1)  → L61371
      "61371"  (L dropped)    → L61371
    Anything else is flagged for the clerk instead of being guessed.
    """
    r = FieldResult(raw=text)
    value = _strip_label(text.strip(), r"inv\s*(no|number)?")
    value = re.sub(r"[^A-Za-z0-9|!]", "", value)
    prefix = prefix.upper()

    # A stray mark read before the prefix ("1L61170", "|L61170") — seen on real RPV crops.
    m = re.fullmatch(rf"[1|!Il]({re.escape(prefix)}\w{{{digits}}})", value, flags=re.IGNORECASE)
    if m:
        r.notes.append(f"Read '{value}': dropped stray character before '{prefix}'")
        value = m.group(1)

    body = value[len(prefix):] if value.upper().startswith(prefix) else None
    if body is not None:
        fixed = body.translate(_DIGIT_FIXES)
        if fixed != body:
            r.notes.append(f"Fixed look-alike characters: '{body}' → '{fixed}'")
        body = fixed
    else:
        digits_only = value.translate(_DIGIT_FIXES)
        if re.fullmatch(rf"1\d{{{digits}}}", digits_only):
            body = digits_only[1:]
            r.notes.append(f"Read '{value}': first '1' is the '{prefix}' prefix")
        elif re.fullmatch(rf"\d{{{digits}}}", digits_only):
            body = digits_only
            r.notes.append(f"Read '{value}': added missing '{prefix}' prefix")
        else:
            body = digits_only

    r.value = prefix + body
    if not value:
        r.issues.append("Invoice number is empty")
        r.value = ""
    elif not re.fullmatch(rf"\d{{{digits}}}", body):
        r.issues.append(f"Invoice '{r.value}' should be {prefix} + {digits} digits")
    return r


# ─── Whole header block ──────────────────────────────────────────────────────

_HEADER_LABELS = {
    "code": r"code",
    "name": r"name",
    "net": r"net(\s*amount)?",
    "inv_no": r"inv\s*no",
}


def split_header_text(text: str) -> dict[str, str]:
    """
    Split OCR text of the whole header block ("Code: APD\\nName: ...\\nNet : 97142.00\\n
    InvNo : L60222") into raw per-field strings (label removed).
    """
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        for key, label in _HEADER_LABELS.items():
            m = re.match(rf"^(?:{label})\s*[:;.]?\s*(?P<value>.*)$", line, flags=re.IGNORECASE)
            if m and key not in out:
                out[key] = m.group("value").strip()
                break
    return out


# ─── Amount in words (Indian system) ─────────────────────────────────────────

_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "ninty": 90,
}
_SCALES = {"thousand": 1_000, "lakh": 100_000, "lakhs": 100_000, "lac": 100_000,
           "lacs": 100_000, "crore": 10_000_000, "crores": 10_000_000}


def words_to_number(text: str) -> Optional[int]:
    """
    "Thirteen Thousand Five Hundred FortySix" → 13546.
    Handles joined words (FortySix) and common spellings (Ninty, Fourty). Paise are ignored.
    Returns None if a word is not understood.
    """
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)  # FortySix → Forty Six
    words = re.findall(r"[a-zA-Z]+", text.lower())
    if "paise" in words or "paisa" in words:
        # "... Rupees X and Y Paise" → keep only the rupee part
        cut = max(i for i, w in enumerate(words) if w == "and") if "and" in words else len(words)
        words = words[:cut]
    total = current = 0
    seen_any = False
    for w in words:
        if w in ("and", "rupees", "rupee", "only", "rs"):
            continue
        if w in _UNITS:
            current += _UNITS[w]
        elif w == "hundred":
            current = (current or 1) * 100
        elif w in _SCALES:
            total += (current or 1) * _SCALES[w]
            current = 0
        else:
            return None
        seen_any = True
    return total + current if seen_any else None
