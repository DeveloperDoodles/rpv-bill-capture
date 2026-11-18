"""
The capture workflow, without any UI: read a bill, check duplicates, save it.

Kept separate from the Tkinter window so it can be tested.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from . import capture
from .bill import Bill, read_bill
from .config import Settings
from .sheet import SheetClient
from .store import AuditLog, PendingQueue


@dataclass
class SaveResult:
    status: str          # "written" | "queued" | "dry_run"
    message: str
    row: Optional[int] = None


@dataclass
class Stats:
    captured: int = 0
    written: int = 0
    queued: int = 0
    skipped: int = 0
    duplicates: int = 0
    reviewed: int = 0


def _same_amount(a: str, b: str) -> bool:
    try:
        return abs(float(str(a).replace(",", "")) - float(str(b).replace(",", ""))) < 0.005
    except ValueError:
        return False


@dataclass
class Session:
    settings: Settings
    calibration: dict
    sheet: Optional[SheetClient] = None
    dry_run: bool = False
    party_codes: dict = field(default_factory=dict)
    audit: AuditLog = field(default_factory=AuditLog)
    queue: PendingQueue = field(default_factory=PendingQueue)
    stats: Stats = field(default_factory=Stats)
    last_written: Optional[tuple] = None   # (row, invoice)
    session_invoices: dict = field(default_factory=dict)  # invoice → where it went

    # ── Reading ──────────────────────────────────────────────────────────

    def read_screen(self, frame=None) -> Bill:
        frame = frame if frame is not None else capture.screenshot()
        bill = read_bill(frame, self.calibration, self.settings, self.party_codes)
        self.stats.captured += 1
        return bill

    # ── Connection ───────────────────────────────────────────────────────

    def try_reconnect(self) -> bool:
        """Reconnect to Google Sheets without ever opening a browser. True if now online."""
        if self.dry_run:
            return False
        if self.sheet and self.sheet.connected:
            return True
        try:
            if self.sheet is None:
                self.sheet = SheetClient(self.settings)
            self.sheet.connect(interactive=False)
            return self.sheet.connected
        except Exception:
            return False

    # ── Duplicates ───────────────────────────────────────────────────────

    def find_duplicates(self, invoice: str, snapshot=None) -> list[str]:
        """Human-readable list of places this invoice already exists."""
        found = []
        if invoice in self.session_invoices:
            found.append(f"already captured this session ({self.session_invoices[invoice]})")
        if self.queue.find_invoice(invoice):
            found.append("waiting in the upload queue")
        if self.sheet and self.sheet.connected:
            try:
                snap = snapshot or self.sheet.snapshot()
                for row, code, net in snap.duplicates(invoice):
                    found.append(f"sheet row {row} ({code}, {net})")
            except Exception as e:
                found.append(f"(could not check the sheet: {e})")
        # De-duplicate the session entry vs. the sheet row it produced
        return list(dict.fromkeys(found))

    # ── Saving ───────────────────────────────────────────────────────────

    def save(self, bill: Bill, duplicate_of: Optional[list] = None) -> SaveResult:
        values = bill.values()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if self.dry_run:
            result = SaveResult("dry_run", "Test mode — not written to the sheet")
        elif not (self.sheet and self.sheet.connected):
            self.queue.add(values, timestamp, "Not connected to Google Sheets", bool(duplicate_of))
            result = SaveResult("queued", "Not connected — saved locally, will upload later")
        else:
            try:
                row = self.sheet.write_bill(values, timestamp)
                result = SaveResult("written", f"Saved to sheet row {row}", row)
                self.last_written = (row, bill.inv_no)
                if duplicate_of:
                    dup_rows = [r for r, _, _ in self.sheet.snapshot().duplicates(bill.inv_no)]
                    try:
                        self.sheet.highlight(sorted(set(dup_rows + [row])))
                    except Exception:
                        pass
            except Exception as e:
                self.queue.add(values, timestamp, f"Write failed: {e}", bool(duplicate_of))
                result = SaveResult("queued", f"Upload failed ({e}) — saved locally, will retry")

        if result.status == "written":
            self.stats.written += 1
        elif result.status == "queued":
            self.stats.queued += 1
        if duplicate_of:
            self.stats.duplicates += 1
        self.session_invoices[bill.inv_no] = result.message
        self._log(bill, "saved", result, duplicate_of)
        return result

    def skip(self, bill: Bill, reason: str = "skipped by clerk") -> None:
        self.stats.skipped += 1
        self._log(bill, "skipped", None, None, reason=reason)

    def _log(self, bill: Bill, action: str, result: Optional[SaveResult], duplicate_of, reason: str = "") -> None:
        try:
            images = self.audit.save_images(bill.images)
            self.audit.record(
                action=action,
                reason=reason,
                values=bill.values(),
                raw_ocr=bill.raw,
                confidence={k: round(v, 1) for k, v in bill.confidence.items()},
                issues=bill.issues,
                notes=bill.notes,
                user_modified=bill.user_modified,
                duplicate_of=duplicate_of or [],
                status=result.status if result else "",
                row=result.row if result else None,
                images=images,
                dry_run=self.dry_run,
            )
        except Exception as e:  # logging must never stop the clerk
            print(f"Warning: could not write audit log: {e}")

    # ── PDF import ───────────────────────────────────────────────────────

    def check_import(self, pdf_bills: list) -> list[dict]:
        """
        Decide what to do with each bill from a PDF.
        Returns [{"pdf": PdfBill, "status": "ready" | "problem" | "duplicate", "detail": str}].
        """
        snap = None
        if self.sheet and self.sheet.connected:
            try:
                snap = self.sheet.snapshot()
            except Exception:
                snap = None
        out = []
        for pb in pdf_bills:
            if not pb.ok:
                out.append({"pdf": pb, "status": "problem", "detail": "; ".join(pb.problems)})
                continue
            dups = [d for d in self.find_duplicates(pb.bill.inv_no, snap) if not d.startswith("(could not")]
            if dups:
                out.append({"pdf": pb, "status": "duplicate", "detail": "already recorded: " + "; ".join(dups)})
            else:
                out.append({"pdf": pb, "status": "ready", "detail": "checks passed"})
        return out

    def save_import(self, items: list[dict], progress=None) -> list[SaveResult]:
        """Save every item whose status is "ready". `progress(i, n)` is called after each."""
        ready = [it for it in items if it["status"] == "ready"]
        results = []
        for i, it in enumerate(ready, 1):
            bill = it["pdf"].bill
            bill.issues = []  # all checks passed; the list held nothing blocking
            res = self.save(bill)
            it["status"] = "saved" if res.status in ("written", "dry_run") else "queued"
            it["detail"] = res.message
            results.append(res)
            if progress:
                progress(i, len(ready))
        for it in items:
            if it["status"] in ("problem", "duplicate"):
                self.skip(it["pdf"].bill, reason=f"PDF import: {it['detail']}")
        return results

    # ── Undo / retry ─────────────────────────────────────────────────────

    def undo_last(self) -> str:
        if not self.last_written:
            return "Nothing to undo."
        row, invoice = self.last_written
        self.sheet.undo(row, invoice)
        self.last_written = None
        self.session_invoices.pop(invoice, None)
        self.stats.written -= 1
        self.audit.record(action="undo", row=row, invoice=invoice)
        return f"Removed {invoice} from row {row}."

    def retry_pending(self) -> tuple[int, int, list[str]]:
        """Upload queued bills. Returns (uploaded, still waiting, messages)."""
        items = self.queue.load()
        if not items:
            return 0, 0, []
        if not (self.sheet and self.sheet.connected):
            return 0, len(items), ["Not connected to Google Sheets."]
        done, msgs = 0, []
        for it in items:
            bill = it["bill"]
            try:
                dups = self.sheet.snapshot().duplicates(bill["inv_no"])
                if any(code == bill["code"] and _same_amount(net, bill["net"]) for _, code, net in dups):
                    self.queue.remove(it["id"])
                    msgs.append(f"{bill['inv_no']}: already in the sheet — removed from queue")
                    done += 1
                    continue
                if dups and not it.get("allow_duplicate"):
                    self.queue.update_reason(it["id"], "Same invoice with different values is in the sheet — check by hand")
                    msgs.append(f"{bill['inv_no']}: different entry already in sheet, left in queue")
                    continue
                row = self.sheet.write_bill(bill, it["timestamp"])
                self.queue.remove(it["id"])
                self.audit.record(action="uploaded_from_queue", values=bill, row=row)
                msgs.append(f"{bill['inv_no']}: uploaded to row {row}")
                done += 1
            except Exception as e:
                self.queue.update_reason(it["id"], f"Retry failed: {e}")
                msgs.append(f"{bill['inv_no']}: still failing ({e})")
        return done, len(self.queue), msgs
