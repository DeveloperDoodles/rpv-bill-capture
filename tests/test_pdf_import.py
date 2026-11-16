"""PDF import tests. Synthetic pages use made-up parties; the real-PDF test runs only if the private file exists."""

import csv
import os
import unittest

from rpv_app.config import Settings
from rpv_app.parse import parse_code, words_to_number
from rpv_app.pdf_import import bills_from_pages, parse_page


def page(inv="L90001", code="ZZ01", party="TEST PHARMA", page_no=1, page_total=1, totals=True,
         taxable="1000.00", gst="50.00", adj="0.40", bill="1050.40", srcn="0.00", net="1050.40",
         words="One Thousand Fifty"):
    head = (f"{party}({code})                   DlNo1: X                      InvNo  : {inv}\n"
            f"ADDRESS LINE                       DlNo2: X                      InvDate: 12-Nov-2026\n"
            f"Ph: 0                              IRNNo:                        PageNo: {page_no} / {page_total}. RemBy:\n"
            f"MFGBy  QTY FREE PRODUCT NAME\n"
            f"ACME    2       SOME TABS   10   100.00 B1 06/28  80.00  70.00  140.00 -1.00 5 300490\n")
    if not totals:
        return head + "Gross :  140.00                 Continued on page No.......2\n"
    return head + (
        "UID:19 Last Receipt Dt:11/4/2026   Amt:1\n"
        "    Gross    Discount    Taxable        GST     SubTotals   Bill Amount   SRCNAmt   NETAmount\n"
        f"GST 0:   0.00   0.00   0.00   0.00 No Of Items:1   Gross:  990.00     {bill}   {srcn}   {net}\n"
        f"GST 5:   990.00   -10.00   {taxable}   {gst}       Disc :   -10.00\n"
        "GST12:   0.00   0.00   0.00   0.00   GST  :  50.00\n"
        f"GST18:   0.00   0.00   0.00   0.00   Adj  :  {adj}\n"
        "GST28:   0.00   0.00   0.00   0.00   TCS  :  0.00\n"
        f"Rupees {words} Only.      OS:1.00  NoBills:1     For SOMEONE\n")


def read(*pages, **kw):
    return bills_from_pages(list(pages), Settings(), kw.get("codes"))


class TestWords(unittest.TestCase):
    def test_examples_from_real_bills(self):
        self.assertEqual(words_to_number("Thirteen Thousand Five Hundred FortySix"), 13546)
        self.assertEqual(words_to_number("TwentyEight Thousand Eight Hundred NintySix"), 28896)
        self.assertEqual(words_to_number("Nine Thousand Five Hundred SixtyThree"), 9563)

    def test_lakh_crore(self):
        self.assertEqual(words_to_number("Two Lakh Forty Six Thousand Three Hundred FortyNine"), 246349)
        self.assertEqual(words_to_number("One Crore Five Lakh"), 10500000)

    def test_paise_ignored(self):
        self.assertEqual(words_to_number("Ten Thousand and Fifty Paise"), 10000)

    def test_unknown_word(self):
        self.assertIsNone(words_to_number("Ten Thousnd"))


class TestPdfBills(unittest.TestCase):
    def test_single_page_bill(self):
        [b] = read(page())
        self.assertTrue(b.ok, b.problems)
        self.assertEqual((b.bill.inv_no, b.bill.code, b.bill.net, b.bill.date, b.bill.name),
                         ("L90001", "ZZ01", "1050.40", "12-Nov-2026", "TEST PHARMA"))

    def test_multi_page_bill_grouped(self):
        bills = read(page(page_no=1, page_total=2, totals=False), page(page_no=2, page_total=2),
                     page(inv="L90002"))
        self.assertEqual([b.bill.inv_no for b in bills], ["L90001", "L90002"])
        self.assertEqual(bills[0].pages, [1, 2])
        self.assertTrue(all(b.ok for b in bills))

    def test_missing_last_page(self):
        [b] = read(page(page_no=1, page_total=2, totals=False))
        self.assertFalse(b.ok)

    def test_missing_first_page(self):
        [b] = read(page(page_no=2, page_total=2))
        self.assertFalse(b.ok)

    def test_totals_dont_add_up(self):
        [b] = read(page(taxable="1100.00"))
        self.assertTrue(any("add up" in p for p in b.problems))

    def test_net_mismatch(self):
        [b] = read(page(srcn="10.00"))
        self.assertTrue(any("NETAmount" in p for p in b.problems))

    def test_credit_note_net(self):
        [b] = read(page(srcn="50.40", net="1000.00"))
        self.assertTrue(b.ok, b.problems)
        self.assertEqual(b.bill.net, "1000.00")

    def test_words_mismatch(self):
        [b] = read(page(words="Two Thousand Fifty"))
        self.assertTrue(any("words" in p for p in b.problems))

    def test_duplicate_in_same_pdf(self):
        bills = read(page(), page(inv="L90002"), page())
        self.assertFalse(bills[2].ok)

    def test_party_code_list(self):
        [b] = read(page(), codes={"AP37": "X"})
        self.assertFalse(b.ok)
        [b] = read(page(), codes={"ZZ01": "OFFICIAL NAME"})
        self.assertTrue(b.ok)
        self.assertEqual(b.bill.name, "OFFICIAL NAME")

    def test_blank_page_ignored(self):
        self.assertEqual(len(read(page(), "\n\n")), 1)

    def test_parse_page_fields(self):
        p = parse_page(page())
        self.assertEqual((p.page_no, p.page_total, p.items), (1, 1, 1))


class TestScreenCodeInBrackets(unittest.TestCase):
    def test_party_line(self):
        self.assertEqual(parse_code("SOME PHARMA DISTRIBUTORS(AP37)").value, "AP37")
        self.assertEqual(parse_code("Code: APD").value, "APD")


class TestRealPdf(unittest.TestCase):
    FOLDER = os.path.join(os.path.dirname(__file__), "data", "pdfs")

    def test_real_batch(self):
        expected_file = os.path.join(self.FOLDER, "expected.csv")
        if not os.path.exists(expected_file):
            self.skipTest("private test PDFs not present")
        try:
            import pypdf  # noqa: F401  (developer-only dependency)
        except ImportError:
            self.skipTest("pypdf not installed")
        from rpv_app.pdf_import import read_pdf
        with open(expected_file, newline="") as f:
            rows = list(csv.DictReader(f))
        by_file = {}
        for r in rows:
            by_file.setdefault(r["file"], []).append(r)
        for fname, exp in by_file.items():
            bills = read_pdf(os.path.join(self.FOLDER, fname), Settings())
            self.assertEqual(len(bills), len(exp), fname)
            for b, e in zip(bills, exp):
                self.assertTrue(b.ok, (e["inv_no"], b.problems))
                self.assertEqual((b.bill.inv_no, b.bill.code, b.bill.net, b.bill.date),
                                 (e["inv_no"], e["code"], e["net"], e["date"]))
                a, _, z = e["pages"].partition("-")
                self.assertEqual(b.pages, list(range(int(a), int(z or a) + 1)))


if __name__ == "__main__":
    unittest.main()
