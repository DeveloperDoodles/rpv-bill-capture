import json
import os
import tempfile
import unittest

from PIL import Image

from rpv_app import capture
from rpv_app.config import Settings, load_party_codes, load_settings


class TestSettings(unittest.TestCase):
    def _write(self, data):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        return path

    def test_defaults_without_file(self):
        s = load_settings("/nonexistent/settings.json")
        self.assertEqual(s.columns["invoice"], "A")

    def test_override_merges_columns(self):
        s = load_settings(self._write({"columns": {"name": "D"}, "_comment": "x"}))
        self.assertEqual(s.columns["name"], "D")
        self.assertEqual(s.columns["invoice"], "A")

    def test_unknown_key_rejected(self):
        with self.assertRaises(ValueError):
            load_settings(self._write({"spreadsheet": "typo"}))

    def test_bad_column_rejected(self):
        with self.assertRaises(ValueError):
            load_settings(self._write({"columns": {"net": "3"}}))

    def test_same_column_twice_rejected(self):
        with self.assertRaises(ValueError):
            load_settings(self._write({"columns": {"name": "A"}}))

    def test_party_codes_csv(self):
        fd, path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, "w") as f:
            f.write("Code,Name\nabc,ABC PHARMA\nXY,XY ASSOCIATES\n\n")
        s = Settings()
        s.party_codes_file = path
        self.assertEqual(load_party_codes(s), {"ABC": "ABC PHARMA", "XY": "XY ASSOCIATES"})


class TestCapture(unittest.TestCase):
    def test_screen_size_check(self):
        frame = Image.new("RGB", (1920, 1080))
        capture.check_screen_matches(frame, {"screen_size": [1920, 1080]})
        with self.assertRaises(capture.ScreenChanged):
            capture.check_screen_matches(frame, {"screen_size": [1366, 768]})

    def test_crop(self):
        frame = Image.new("RGB", (100, 100))
        self.assertEqual(capture.crop(frame, {"x1": 10, "y1": 20, "x2": 30, "y2": 60}).size, (20, 40))


class TestOcrOnRealCrops(unittest.TestCase):
    """Runs only when Tesseract and the (private, git-ignored) test crops are available."""

    FOLDER = os.path.join(os.path.dirname(__file__), "data", "header_crops")

    def test_no_silent_errors(self):
        from rpv_app import accuracy, ocr
        if not os.path.exists(os.path.join(self.FOLDER, "ground_truth.csv")):
            self.skipTest("no test crops")
        try:
            ocr.setup_tesseract(Settings())
        except ocr.TesseractMissing:
            self.skipTest("Tesseract not installed")
        self.assertEqual(accuracy.run(self.FOLDER, Settings()), 0)


class TestScreenNewLayout(unittest.TestCase):
    """Screen reading on PDF pages rendered at screen resolution (private, git-ignored data).
    Pages with no amount (page 1 of 2) must be flagged; others must be correct or flagged."""

    FOLDER = os.path.join(os.path.dirname(__file__), "data", "screen_pages")

    def test_no_silent_errors(self):
        import csv
        from rpv_app import ocr
        from rpv_app.bill import read_bill
        if not os.path.exists(os.path.join(self.FOLDER, "expected.csv")):
            self.skipTest("no rendered pages")
        try:
            ocr.setup_tesseract(Settings())
        except ocr.TesseractMissing:
            self.skipTest("Tesseract not installed")
        with open(os.path.join(self.FOLDER, "calibration.json")) as f:
            cal = json.load(f)
        with open(os.path.join(self.FOLDER, "expected.csv"), newline="") as f:
            rows = list(csv.DictReader(f))
        auto_ok = 0
        for r in rows:
            b = read_bill(Image.open(os.path.join(self.FOLDER, r["file"])).convert("RGB"), cal, Settings())
            correct = (b.inv_no, b.code, b.net) == (r["inv_no"], r["code"], r["net"])
            if not r["net"]:
                self.assertTrue(b.needs_review, r["file"])
            else:
                self.assertTrue(correct or b.needs_review, (r["file"], b.values()))
                auto_ok += correct and not b.needs_review
        self.assertGreaterEqual(auto_ok, 6)  # most clean bills should pass without the clerk


if __name__ == "__main__":
    unittest.main()
