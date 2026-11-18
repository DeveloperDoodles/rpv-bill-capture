import os
import tempfile
import time
import unittest

from rpv_app import qol
from rpv_app.bill import Bill, apply_parse, check_confidence
from rpv_app.config import Settings


class TestHotkey(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(qol.parse_hotkey("F9"), (0, 0x78))
        self.assertEqual(qol.parse_hotkey("ctrl+shift+F2"), (6, 0x71))
        self.assertIsNone(qol.parse_hotkey(""))
        self.assertIsNone(qol.parse_hotkey("F13"))
        self.assertIsNone(qol.parse_hotkey("Win+F9"))

    def test_disabled_or_bad_hotkey_never_crashes(self):
        self.assertFalse(qol.GlobalHotkey("").ok)
        h = qol.GlobalHotkey("nonsense")
        self.assertFalse(h.ok)
        self.assertTrue(h.error)
        self.assertFalse(h.pressed())
        h.stop()


class TestWindowState(unittest.TestCase):
    def test_round_trip(self):
        path = os.path.join(tempfile.mkdtemp(), "ui.json")
        self.assertEqual(qol.load_ui_state(path), {})
        qol.save_ui_state({"x": 10, "y": 20}, path)
        qol.save_ui_state({"y": 30}, path)
        self.assertEqual(qol.load_ui_state(path), {"x": 10, "y": 30})

    def test_off_screen_position_rejected(self):
        self.assertTrue(qol.position_on_screen(100, 100, 1920, 1080))
        self.assertFalse(qol.position_on_screen(2500, 100, 1920, 1080))  # was on a second monitor
        self.assertFalse(qol.position_on_screen(100, -50, 1920, 1080))


class TestSingleInstance(unittest.TestCase):
    def test_second_copy_refused(self):
        port = 47000 + os.getpid() % 1000
        a = qol.SingleInstance(port)
        b = qol.SingleInstance(port)
        try:
            self.assertTrue(a.ok)
            self.assertFalse(b.ok)
        finally:
            a.release()
            b.release()
        c = qol.SingleInstance(port)
        self.assertTrue(c.ok)
        c.release()


class TestCleanup(unittest.TestCase):
    def test_old_logs_removed_queue_kept(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "crops"))
        old, new = time.time() - 100 * 86400, time.time()
        files = {"audit-2026-01-01.jsonl": old, "audit-2026-11-18.jsonl": new,
                 "pending_writes.jsonl": old, "crops/a.png": old, "crops/b.png": new}
        for name, t in files.items():
            p = os.path.join(d, name)
            open(p, "w").close()
            os.utime(p, (t, t))
        self.assertEqual(qol.cleanup_logs(90, d), 2)
        left = sorted(os.listdir(d)) + sorted(os.listdir(os.path.join(d, "crops")))
        self.assertEqual(left, ["audit-2026-11-18.jsonl", "crops", "pending_writes.jsonl", "b.png"])
        self.assertEqual(qol.cleanup_logs(0, d), 0)


class TestVersions(unittest.TestCase):
    def test_compare(self):
        self.assertTrue(qol.newer_version_available("2.10.0", "2.9.1"))
        self.assertFalse(qol.newer_version_available("2.1.0", "2.1.0"))
        self.assertFalse(qol.newer_version_available(None, "2.1.0"))
        self.assertFalse(qol.newer_version_available("2.0.9", "2.1.0"))


class TestProblemFields(unittest.TestCase):
    def test_marks_only_doubtful_fields(self):
        b = Bill()
        b.confidence = {"code": 95, "net": 40, "inv_no": 95}
        apply_parse(b, {"code": "ABC", "net": "1234.00", "inv_no": "L1234"}, Settings(), None)
        check_confidence(b, Settings())
        self.assertEqual(b.problem_fields, {"net", "inv_no"})


class TestReconnect(unittest.TestCase):
    def test_dry_run_and_no_login_never_open_browser(self):
        from rpv_app.session import Session
        from rpv_app.store import AuditLog, PendingQueue
        d = tempfile.mkdtemp()
        st = Settings()
        st.spreadsheet_id = "x" * 30
        st.oauth_token_file = os.path.join(d, "no_token.json")
        st.oauth_client_file = os.path.join(d, "no_client.json")
        s = Session(st, {}, dry_run=True, audit=AuditLog(d), queue=PendingQueue(d + "/q.jsonl"))
        self.assertFalse(s.try_reconnect())
        s.dry_run = False
        self.assertFalse(s.try_reconnect())  # no token → gives up quietly, no browser


if __name__ == "__main__":
    unittest.main()
