"""
Read bills straight from a PDF printed out of RPV ("Microsoft Print to PDF").

The PDF contains the real text, so there is no OCR guessing. Each bill is still
cross-checked before it is allowed into the sheet:
  - taxable + GST + Adj + TCS  must equal  Bill Amount
  - Bill Amount − SRCNAmt      must equal  NETAmount
  - the amount in words ("Rupees Thirteen Thousand ... Only") must match
  - every page of a multi-page bill (PageNo 1/2, 2/2) must be present
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from .bill import Bill
from .config import Settings
from .parse import parse_code, parse_invoice, words_to_number

_NUM = r"-?\d[\d,]*\.\d{2}"


@dataclass
class PageInfo:
    page_index: int          # 0-based page in the PDF
    invoice: str = ""
    party: str = ""
    code: str = ""
    date: str = ""
    page_no: int = 0
    page_total: int = 0
    has_totals: bool = False
    bill_amount: Optional[Decimal] = None
    srcn: Optional[Decimal] = None
    net: Optional[Decimal] = None
    taxable: Decimal = Decimal("0")
    gst: Decimal = Decimal("0")
    adj: Decimal = Decimal("0")
    tcs: Decimal = Decimal("0")
    words: str = ""
    items: Optional[int] = None
    problems: list = field(default_factory=list)


def _dec(s: str) -> Decimal:
    return Decimal(s.replace(",", ""))


def parse_page(text: str, page_index: int = 0) -> PageInfo:
    p = PageInfo(page_index=page_index)
    lines = [ln.rstrip() for ln in text.splitlines()]
    first = next((ln.strip() for ln in lines if ln.strip()), "")

    m = re.match(r"^(?P<name>[^()]+?)\s*\((?P<code>[A-Za-z0-9 ]+)\)", first)
    if m:
        p.party, p.code = m.group("name").strip(), m.group("code").replace(" ", "").upper()
    else:
        p.problems.append("party name / code line not found")

    m = re.search(r"InvNo\s*:\s*(\S+)", text)
    p.invoice = m.group(1).strip().upper() if m else ""
    if not m:
        p.problems.append("invoice number not found")

    m = re.search(r"InvDate\s*:\s*(\d{1,2}-[A-Za-z]{3}-\d{4})", text)
    p.date = m.group(1) if m else ""

    m = re.search(r"PageNo\s*:\s*(\d+)\s*/\s*(\d+)", text)
    if m:
        p.page_no, p.page_total = int(m.group(1)), int(m.group(2))
    else:
        p.problems.append("page number not found")

    for ln in lines:
        g = re.match(rf"^\s*GST\s*\d+\s*:\s*({_NUM})\s+({_NUM})\s+({_NUM})\s+({_NUM})", ln)
        if g:
            p.taxable += _dec(g.group(3))
            p.gst += _dec(g.group(4))
        if "No Of Items" in ln:
            p.has_totals = True
            m = re.search(r"No Of Items\s*:\s*(\d+)", ln)
            p.items = int(m.group(1)) if m else None
            after = ln.split("Gross", 1)[1] if "Gross" in ln else ln
            nums = re.findall(_NUM, after)
            # after "Gross: <gross>" come Bill Amount, SRCNAmt, NETAmount
            if len(nums) >= 4:
                p.bill_amount, p.srcn, p.net = (_dec(x) for x in nums[-3:])
            else:
                p.problems.append("Bill Amount / NETAmount numbers not found")

    m = re.search(rf"Adj\s*:\s*({_NUM})", text)
    p.adj = _dec(m.group(1)) if m else Decimal("0")
    m = re.search(rf"TCS\s*:\s*({_NUM})", text)
    p.tcs = _dec(m.group(1)) if m else Decimal("0")
    m = re.search(r"Rupees\s+(.+?)\s+Only", text, flags=re.IGNORECASE)
    p.words = m.group(1).strip() if m else ""
    return p


@dataclass
class PdfBill:
    bill: Bill
    pages: list           # 1-based PDF page numbers
    problems: list        # anything here blocks saving
    checks: list          # checks that passed, for the log

    @property
    def ok(self) -> bool:
        return not self.problems


def extract_text_pages(path: str) -> list[str]:
    from pypdf import PdfReader
    reader = PdfReader(path)
    return [page.extract_text(extraction_mode="layout") or "" for page in reader.pages]


def bills_from_pages(texts: list[str], settings: Settings, party_codes: Optional[dict] = None,
                     source: str = "") -> list[PdfBill]:
    pages = [parse_page(t, i) for i, t in enumerate(texts)]
    # Group consecutive pages of the same invoice.
    groups: list[list[PageInfo]] = []
    for p in pages:
        if not p.invoice and not p.code and not p.has_totals:
            continue  # blank / non-bill page
        if groups and groups[-1][0].invoice == p.invoice and p.invoice:
            groups[-1].append(p)
        else:
            groups.append([p])

    seen: dict[str, int] = {}
    out = []
    for grp in groups:
        out.append(_build_bill(grp, settings, party_codes, source, seen))
    return out


def _build_bill(grp: list[PageInfo], settings: Settings, party_codes, source, seen) -> PdfBill:
    problems, checks = [], []
    first, last = grp[0], grp[-1]
    for p in grp:
        problems += [f"page {p.page_index + 1}: {x}" for x in p.problems]

    inv = parse_invoice(first.invoice, settings.invoice_prefix, settings.invoice_digits)
    problems += inv.issues
    code = parse_code(f"{first.code}", party_codes)
    problems += code.issues

    # Pages complete and consistent
    total = first.page_total
    got = [p.page_no for p in grp]
    if total and got != list(range(1, total + 1)):
        problems.append(f"pages {got} of {total} — part of this bill is missing from the PDF")
    if len({p.code for p in grp}) > 1:
        problems.append("party code differs between pages")
    totals_pages = [p for p in grp if p.has_totals]
    if not totals_pages:
        problems.append("no totals page (Bill Amount) found")
    t = totals_pages[-1] if totals_pages else last

    net_value = ""
    if t.bill_amount is not None:
        calc = t.taxable + t.gst + t.adj + t.tcs
        if abs(calc - t.bill_amount) > Decimal("0.011"):
            problems.append(f"totals don't add up: taxable+GST+adj+TCS = {calc}, Bill Amount = {t.bill_amount}")
        else:
            checks.append("taxable + GST + adj + TCS = Bill Amount")
        if t.net is not None and t.srcn is not None:
            if abs((t.bill_amount - t.srcn) - t.net) > Decimal("0.011"):
                problems.append(f"Bill Amount − SRCNAmt ≠ NETAmount ({t.bill_amount} − {t.srcn} ≠ {t.net})")
            else:
                checks.append("Bill Amount − SRCNAmt = NETAmount")
            net_value = f"{t.net:.2f}"
        if t.words:
            in_words = words_to_number(t.words)
            if in_words is None:
                checks.append(f"amount in words not understood: '{t.words}'")
            elif in_words != int(t.bill_amount):
                problems.append(f"amount in words ({in_words}) ≠ Bill Amount ({t.bill_amount})")
            else:
                checks.append("amount in words matches")
        if t.net is not None and t.net <= 0:
            problems.append("NETAmount is zero or negative")

    if inv.value in seen:
        problems.append(f"same invoice appears twice in this PDF (also at page {seen[inv.value]})")
    seen.setdefault(inv.value, first.page_index + 1)

    bill = Bill(code=code.value, net=net_value, inv_no=inv.value, name=first.party, date=first.date)
    bill.confidence = {"code": 100.0, "net": 100.0, "inv_no": 100.0}
    bill.raw = {"source": os.path.basename(source), "pages": [p.page_index + 1 for p in grp],
                "bill_amount": str(t.bill_amount), "srcn": str(t.srcn), "words": t.words}
    bill.issues = list(problems)
    bill.notes = list(checks)
    if party_codes and bill.code in party_codes and party_codes[bill.code]:
        bill.name = party_codes[bill.code]
    return PdfBill(bill=bill, pages=[p.page_index + 1 for p in grp], problems=problems, checks=checks)


def read_pdf(path: str, settings: Settings, party_codes: Optional[dict] = None) -> list[PdfBill]:
    return bills_from_pages(extract_text_pages(path), settings, party_codes, source=path)
