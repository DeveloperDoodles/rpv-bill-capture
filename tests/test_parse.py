import unittest

from rpv_app.parse import closest_code, parse_code, parse_invoice, parse_net, split_header_text


class TestInvoice(unittest.TestCase):
    def test_clean(self):
        r = parse_invoice("L61371")
        self.assertEqual(r.value, "L61371")
        self.assertTrue(r.ok)

    def test_label_removed(self):
        self.assertEqual(parse_invoice("InvNo : L60222").value, "L60222")

    def test_L_read_as_1(self):
        r = parse_invoice("161371")
        self.assertEqual(r.value, "L61371")
        self.assertTrue(r.ok)
        self.assertTrue(r.notes)

    def test_L_dropped(self):
        r = parse_invoice("61371")
        self.assertEqual(r.value, "L61371")
        self.assertTrue(r.ok)

    def test_stray_mark_before_L(self):
        r = parse_invoice("1L61170")
        self.assertEqual(r.value, "L61170")
        self.assertTrue(r.ok)

    def test_lookalike_letters_in_digits(self):
        r = parse_invoice("L6O2I4")
        self.assertEqual(r.value, "L60214")
        self.assertTrue(r.ok)

    def test_old_bug_does_not_eat_a_digit(self):
        # The old code replaced the first char with L, turning "6137" into "L137".
        r = parse_invoice("6137")
        self.assertFalse(r.ok)

    def test_wrong_length_flagged(self):
        self.assertFalse(parse_invoice("L613711").ok)
        self.assertFalse(parse_invoice("L6137").ok)

    def test_empty(self):
        r = parse_invoice("")
        self.assertFalse(r.ok)
        self.assertEqual(r.value, "")

    def test_configurable_digits(self):
        self.assertTrue(parse_invoice("L100000", digits=6).ok)


class TestNet(unittest.TestCase):
    def test_clean(self):
        r = parse_net("97142.00")
        self.assertEqual(r.value, "97142.00")
        self.assertTrue(r.ok)

    def test_label_and_spaces(self):
        self.assertEqual(parse_net("Net :   68275.00").value, "68275.00")

    def test_indian_commas(self):
        r = parse_net("2,46,349.00")
        self.assertEqual(r.value, "246349.00")
        self.assertTrue(r.ok)

    def test_missing_decimal_flagged(self):
        r = parse_net("6827500")
        self.assertFalse(r.ok)

    def test_missing_decimal_allowed_when_configured(self):
        self.assertTrue(parse_net("68275", require_decimals=False).ok)

    def test_lookalike_letters_flagged(self):
        r = parse_net("68Z75.00")
        self.assertEqual(r.value, "68275.00")
        self.assertFalse(r.ok)  # money: fixed, but the clerk must confirm

    def test_one_decimal_flagged(self):
        self.assertFalse(parse_net("68275.0").ok)

    def test_zero_and_huge(self):
        self.assertFalse(parse_net("0.00").ok)
        self.assertFalse(parse_net("999999999.00", max_amount=1e8).ok)

    def test_empty(self):
        self.assertFalse(parse_net("").ok)

    def test_junk_around_number(self):
        self.assertFalse(parse_net("68275.00 xyz").ok)


class TestCode(unittest.TestCase):
    CODES = {"APD": "ABC PHARMA DISTRIBUTORS", "GA": "XY ASSOCIATES", "RKKM": "", "RGS": ""}

    def test_clean(self):
        self.assertEqual(parse_code("Code: apd").value, "APD")

    def test_in_list(self):
        self.assertTrue(parse_code("APD", self.CODES).ok)

    def test_not_in_list_with_suggestion(self):
        r = parse_code("APO", self.CODES)
        self.assertFalse(r.ok)
        self.assertIn("APD", r.issues[0])

    def test_no_list_format_only(self):
        self.assertTrue(parse_code("NAV").ok)
        self.assertFalse(parse_code("").ok)
        self.assertFalse(parse_code("123").ok)

    def test_closest_ambiguous_returns_none(self):
        self.assertIsNone(closest_code("RG", {"RGS": "", "RGA": ""}))


class TestHeader(unittest.TestCase):
    def test_split(self):
        text = "Code: APD\nName: ABC PHARMA DISTRIBUTORS\nNet : 97142.00\nInvNo : L60222\n 01-05-2026"
        out = split_header_text(text)
        self.assertEqual(out["code"], "APD")
        self.assertEqual(out["name"], "ABC PHARMA DISTRIBUTORS")
        self.assertEqual(out["net"], "97142.00")
        self.assertEqual(out["inv_no"], "L60222")

    def test_missing_lines(self):
        out = split_header_text("garbage\nInvNo : L41112")
        self.assertEqual(out, {"inv_no": "L41112"})


if __name__ == "__main__":
    unittest.main()
