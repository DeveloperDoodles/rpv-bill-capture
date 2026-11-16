"""Tests for the Sheets logic and the capture session, using a fake in-memory sheet."""

import os
import re
import tempfile
import unittest

from rpv_app.bill import Bill
from rpv_app.config import Settings
from rpv_app.session import Session
from rpv_app.sheet import SheetClient, col_to_index
from rpv_app.store import AuditLog, PendingQueue


class FakeWorksheet:
    """Just enough of gspread.Worksheet for SheetClient."""

    id = 0

    def __init__(self, rows=None):
        self.cells = {}  # (row, "A") → value
        self.fail_writes = 0
        self.steal_next_row_once = None  # simulate another machine writing the same row
        for r, row in enumerate(rows or [], start=1):
            for c, v in row.items():
                self.cells[(r, c)] = v
        self.spreadsheet = self
        self.highlighted = []

    def batch_get(self, ranges, major_dimension=None, value_render_option=None):
        out = []
        for rng in ranges:
            m = re.fullmatch(r"([A-Z]+)(\d+):([A-Z]+)", rng)
            if m:  # e.g. "G2:G" → rows of one column
                col, start = m.group(1), int(m.group(2))
                rows = [r for (r, c) in self.cells if c == col and r >= start]
                out.append([[self.cells.get((r, col), "")] for r in range(start, max(rows, default=start - 1) + 1)])
                continue
            m = re.fullmatch(r"([A-Z]+):([A-Z]+)", rng)
            if m:
                col = m.group(1)
                rows = [r for (r, c) in self.cells if c == col and str(self.cells[(r, c)]) != ""]
                height = max(rows, default=0)
                values = [str(self.cells.get((r, col), "")) for r in range(1, height + 1)]
                out.append([values] if values else [])
            else:
                m = re.fullmatch(r"([A-Z]+)(\d+)", rng)
                v = self.cells.get((int(m.group(2)), m.group(1)), "")
                out.append([[str(v)]] if str(v) != "" else [])
        return out

    def batch_update(self, updates, value_input_option=None):
        if isinstance(updates, dict):  # spreadsheet-level formatting call
            self.highlighted.append(updates)
            return
        if self.fail_writes:
            self.fail_writes -= 1
            raise ConnectionError("network down")
        for u in updates:
            m = re.fullmatch(r"([A-Z]+)(\d+)", u["range"])
            self.cells[(int(m.group(2)), m.group(1))] = u["values"][0][0]
        if self.steal_next_row_once:
            row = int(re.fullmatch(r"[A-Z]+(\d+)", updates[0]["range"]).group(1))
            other = self.steal_next_row_once
            self.steal_next_row_once = None
            for c, v in other.items():
                self.cells[(row, c)] = v

    def batch_clear(self, ranges):
        for rng in ranges:
            m = re.fullmatch(r"([A-Z]+)(\d+)", rng)
            self.cells.pop((int(m.group(2)), m.group(1)), None)


HEADER = {"A": "Invoice", "B": "Code", "C": "Amount"}


def make_client(rows=None) -> tuple[SheetClient, FakeWorksheet]:
    ws = FakeWorksheet([HEADER] + (rows or []))
    client = SheetClient(Settings(), worksheet=ws)
    client.machine = "TEST-PC"
    client.sleep = lambda s: None
    return client, ws


class TestSheet(unittest.TestCase):
    def test_col_to_index(self):
        self.assertEqual(col_to_index("A"), 1)
        self.assertEqual(col_to_index("Q"), 17)
        self.assertEqual(col_to_index("AB"), 28)

    def test_next_empty_row_fills_gap(self):
        client, _ = make_client([{"A": "L1", "B": "X", "C": "1"}, {}, {"A": "L3", "B": "Y", "C": "3"}])
        self.assertEqual(client.snapshot().next_empty_row, 3)

    def test_next_empty_row_after_data(self):
        client, _ = make_client([{"A": "L1", "B": "X", "C": "1"}])
        self.assertEqual(client.snapshot().next_empty_row, 3)

    def test_other_columns_do_not_block_row(self):
        # Column D has a formula/note in row 2 — row 2 still counts as free for us.
        client, _ = make_client([{"D": "note"}])
        self.assertEqual(client.snapshot().next_empty_row, 2)

    def test_write_bill_columns(self):
        client, ws = make_client()
        row = client.write_bill({"inv_no": "L61371", "code": "RKKM", "net": "246349.00"}, "2026-11-12 10:00:00")
        self.assertEqual(row, 2)
        self.assertEqual(ws.cells[(2, "A")], 61371)     # like the sheet: number, no "L"
        self.assertEqual(ws.cells[(2, "B")], "RKKM")
        self.assertEqual(ws.cells[(2, "C")], 246349.0)  # a number, not text
        self.assertEqual(ws.cells[(2, "G")], "10:00:00")  # time only, like the existing rows
        self.assertEqual(ws.cells[(2, "Q")], "TEST-PC")
        for c in "DEFHIN":
            self.assertNotIn((2, c), ws.cells)  # rack / diff columns untouched

    def test_header_row_never_written(self):
        client, ws = make_client()
        with self.assertRaises(Exception):
            client._write_row(1, {"invoice": 1})
        self.assertEqual(ws.cells[(1, "A")], "Invoice")

    def test_timestamp_auto_detects_datetime(self):
        client, ws = make_client([{"A": "1", "B": "X", "C": "1", "G": 46000.35}])
        client.write_bill({"inv_no": "L2", "code": "A", "net": "1.00"}, "2026-11-12 10:00:00")
        self.assertEqual(ws.cells[(3, "G")], "2026-11-12 10:00:00")

    def test_timestamp_auto_detects_time(self):
        client, ws = make_client([{"A": "1", "B": "X", "C": "1", "G": 0.35}])
        client.write_bill({"inv_no": "L2", "code": "A", "net": "1.00"}, "2026-11-12 10:00:00")
        self.assertEqual(ws.cells[(3, "G")], "10:00:00")

    def test_prefix_kept_if_configured(self):
        st = Settings()
        st.sheet_invoice_with_prefix = True
        ws = FakeWorksheet([HEADER])
        client = SheetClient(st, worksheet=ws)
        client.sleep = lambda x: None
        client.write_bill({"inv_no": "L61371", "code": "A", "net": "1.00"}, "t")
        self.assertEqual(ws.cells[(2, "A")], "L61371")

    def test_machine_name_setting(self):
        st = Settings()
        st.machine_name = "Counter 2"
        ws = FakeWorksheet([HEADER])
        client = SheetClient(st, worksheet=ws)
        client.sleep = lambda x: None
        client.write_bill({"inv_no": "L61371", "code": "A", "net": "1.00"}, "t")
        self.assertEqual(ws.cells[(2, "Q")], "Counter 2")

    def test_row_with_only_our_timestamp_is_not_free(self):
        client, _ = make_client([{"G": "8:21:14"}])
        self.assertEqual(client.snapshot().next_empty_row, 3)

    def test_rack_columns_do_not_block_row(self):
        client, _ = make_client([{"E": "Rack person", "N": "0:13:07"}])
        self.assertEqual(client.snapshot().next_empty_row, 2)

    def test_custom_columns(self):
        s = Settings()
        s.columns = dict(s.columns, name="D", machine="")
        ws = FakeWorksheet([HEADER])
        client = SheetClient(s, worksheet=ws)
        client.sleep = lambda x: None
        client.write_bill({"inv_no": "L1", "code": "A", "net": "1.00", "name": "ACME"}, "t")
        self.assertEqual(ws.cells[(2, "D")], "ACME")
        self.assertNotIn((2, "Q"), ws.cells)

    def test_row_stolen_by_other_machine_is_retried(self):
        client, ws = make_client()
        ws.steal_next_row_once = {"A": "L99999", "B": "ZZ", "C": "5", "Q": "OTHER-PC"}
        row = client.write_bill({"inv_no": "L61371", "code": "RKKM", "net": "1.00"}, "t")
        self.assertEqual(row, 3)
        self.assertEqual(ws.cells[(2, "A")], "L99999")  # other machine's bill kept
        self.assertEqual(ws.cells[(3, "A")], 61371)  # ours moved to next row

    def test_duplicates(self):
        client, _ = make_client([{"A": "L61371", "B": "RKKM", "C": "246349"}])
        self.assertEqual(client.snapshot().duplicates("l61371"), [(2, "RKKM", "246349")])
        self.assertEqual(client.snapshot().duplicates("L00000"), [])

    def test_duplicates_sheet_without_prefix(self):
        # The real sheet stores 81678; the screen shows L81678.
        client, _ = make_client([{"A": "81678", "B": "PQR", "C": "11653"}])
        self.assertEqual(client.snapshot().duplicates("L81678"), [(2, "PQR", "11653")])

    def test_undo_only_if_unchanged(self):
        client, ws = make_client()
        row = client.write_bill({"inv_no": "L1", "code": "A", "net": "1.00"}, "t")
        ws.cells[(row, "A")] = "L2"
        with self.assertRaises(Exception):
            client.undo(row, "L1")
        ws.cells[(row, "A")] = "L1"
        client.undo(row, "L1")
        self.assertNotIn((row, "A"), ws.cells)


def make_session(client=None, dry_run=False):
    tmp = tempfile.mkdtemp()
    return Session(Settings(), calibration={}, sheet=client, dry_run=dry_run,
                   audit=AuditLog(os.path.join(tmp, "logs")),
                   queue=PendingQueue(os.path.join(tmp, "logs", "pending.jsonl")))


def bill(inv="L61371", code="RKKM", net="246349.00"):
    return Bill(code=code, net=net, inv_no=inv)


class TestSession(unittest.TestCase):
    def test_save_written(self):
        client, ws = make_client()
        s = make_session(client)
        r = s.save(bill())
        self.assertEqual((r.status, r.row), ("written", 2))
        self.assertEqual(s.stats.written, 1)

    def test_dry_run_writes_nothing(self):
        client, ws = make_client()
        s = make_session(client, dry_run=True)
        self.assertEqual(s.save(bill()).status, "dry_run")
        self.assertNotIn((2, "A"), ws.cells)

    def test_offline_queues_then_uploads(self):
        s = make_session(None)
        self.assertEqual(s.save(bill()).status, "queued")
        self.assertEqual(len(s.queue), 1)
        client, ws = make_client()
        s.sheet = client
        done, left, _ = s.retry_pending()
        self.assertEqual((done, left), (1, 0))
        self.assertEqual(ws.cells[(2, "A")], 61371)

    def test_failed_write_is_queued_not_lost(self):
        client, ws = make_client()
        ws.fail_writes = 1
        s = make_session(client)
        r = s.save(bill())
        self.assertEqual(r.status, "queued")
        self.assertEqual(len(s.queue), 1)

    def test_retry_does_not_double_write(self):
        # The write reached the sheet but the reply was lost → queue item must not be written twice.
        client, ws = make_client([{"A": "L61371", "B": "RKKM", "C": "246,349.00"}])
        s = make_session(client)
        s.queue.add(bill().values(), "t", "lost reply")
        done, left, msgs = s.retry_pending()
        self.assertEqual((done, left), (1, 0))
        self.assertNotIn((3, "A"), ws.cells)

    def test_retry_conflicting_duplicate_left_for_human(self):
        client, ws = make_client([{"A": "L61371", "B": "GA", "C": "5.00"}])
        s = make_session(client)
        s.queue.add(bill().values(), "t", "offline")
        done, left, _ = s.retry_pending()
        self.assertEqual((done, left), (0, 1))

    def test_find_duplicates_sheet_and_session(self):
        client, _ = make_client([{"A": "L61371", "B": "RKKM", "C": "1"}])
        s = make_session(client)
        self.assertTrue(any("row 2" in d for d in s.find_duplicates("L61371")))
        s.save(bill(inv="L11111"))
        self.assertTrue(any("this session" in d for d in s.find_duplicates("L11111")))
        self.assertEqual(s.find_duplicates("L22222"), [])

    def test_duplicate_highlighted(self):
        client, ws = make_client([{"A": "L61371", "B": "RKKM", "C": "1"}])
        s = make_session(client)
        s.save(bill(), duplicate_of=["sheet row 2"])
        self.assertTrue(ws.highlighted)

    def test_undo_last(self):
        client, ws = make_client()
        s = make_session(client)
        s.save(bill())
        s.undo_last()
        self.assertNotIn((2, "A"), ws.cells)
        self.assertIsNone(s.last_written)

    def test_audit_log_written(self):
        client, _ = make_client()
        s = make_session(client)
        s.save(bill())
        s.skip(bill(inv="L2"))
        files = [f for f in os.listdir(s.audit.folder) if f.startswith("audit-")]
        self.assertEqual(len(files), 1)
        with open(os.path.join(s.audit.folder, files[0])) as f:
            self.assertEqual(len(f.readlines()), 2)


if __name__ == "__main__":
    unittest.main()


class TestPdfImportSession(unittest.TestCase):
    def _bills(self):
        from tests.test_pdf_import import page
        from rpv_app.pdf_import import bills_from_pages
        return bills_from_pages([page(inv="L90001"), page(inv="L90002", taxable="1.00"), page(inv="L61371")],
                                Settings())

    def test_check_and_save(self):
        client, ws = make_client([{"A": "L61371", "B": "RKKM", "C": "1"}])
        s = make_session(client)
        items = s.check_import(self._bills())
        self.assertEqual([it["status"] for it in items], ["ready", "problem", "duplicate"])
        s.save_import(items)
        self.assertEqual([it["status"] for it in items], ["saved", "problem", "duplicate"])
        self.assertEqual(ws.cells[(3, "A")], 90001)
        self.assertEqual(ws.cells[(3, "C")], 1050.4)
        self.assertNotIn((4, "A"), ws.cells)  # problem and duplicate bills not written
        self.assertEqual((s.stats.written, s.stats.skipped), (1, 2))

    def test_reimport_same_pdf_is_all_duplicates(self):
        client, ws = make_client()
        s = make_session(client)
        s.save_import(s.check_import(self._bills()))
        again = s.check_import(self._bills())
        self.assertEqual(again[0]["status"], "duplicate")

    def test_date_column(self):
        st = Settings()
        st.columns = dict(st.columns, date="E")
        ws = FakeWorksheet([HEADER])
        client = SheetClient(st, worksheet=ws)
        client.sleep = lambda x: None
        s = make_session(client)
        s.save_import(s.check_import(self._bills()[:1]))
        self.assertEqual(ws.cells[(2, "E")], "12-Nov-2026")
