"""
Google Sheets access: find the next free row, detect duplicates, write a bill,
and undo the last write.

Multi-machine safety: after writing, the row is read back. If another machine
wrote to the same row at the same moment, the bill is re-written to the next
free row instead of being lost.
"""

from __future__ import annotations

import os
import random
import socket
import time
from dataclasses import dataclass
from typing import Callable, Optional

from .config import Settings

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]  # Sheets only — no Drive access


class SheetError(RuntimeError):
    pass


def col_to_index(col: str) -> int:
    """'A' → 1, 'Q' → 17, 'AB' → 28."""
    n = 0
    for ch in col.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


def invoice_key(invoice, prefix: str = "L") -> str:
    """'L81678', 'l81678', '81678', 81678 → '81678' so the sheet and the screen compare equal."""
    s = str(invoice).strip().upper()
    if s.endswith(".0"):
        s = s[:-2]
    p = prefix.upper()
    return s[len(p):] if p and s.startswith(p) else s


@dataclass
class Snapshot:
    """What the sheet looked like when we last read it."""
    next_empty_row: int
    rows_by_invoice: dict  # invoice key → [(row, code, net), ...]
    prefix: str = "L"

    def duplicates(self, invoice: str) -> list[tuple[int, str, str]]:
        return self.rows_by_invoice.get(invoice_key(invoice, self.prefix), [])


def default_token_path() -> str:
    """Per-user location, so copying the project folder never copies the login."""
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "RPVBillOCR", "token.json")


class SheetClient:
    def __init__(self, settings: Settings, worksheet=None):
        self.s = settings
        self.cols = {k: v for k, v in settings.columns.items() if v}
        self.machine = settings.machine_name.strip() or socket.gethostname()
        self._time_only: Optional[bool] = None
        self.ws = worksheet          # can be injected for tests
        self.title = ""
        self.sleep: Callable[[float], None] = time.sleep

    # ── Connection ───────────────────────────────────────────────────────

    def _credentials(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        token_path = self.s.oauth_token_file or default_token_path()
        creds = None
        if os.path.exists(token_path):
            try:
                creds = Credentials.from_authorized_user_file(token_path, SCOPES)
            except Exception:
                creds = None
        if creds and creds.valid:
            return creds
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None
        if not creds or not creds.valid:
            if not os.path.exists(self.s.oauth_client_file):
                raise SheetError(
                    f"Google login file not found:\n{self.s.oauth_client_file}\n"
                    "Put the OAuth client_secret.json there (see README.md → 'Google setup')."
                )
            print("Opening your browser to log in to Google…")
            flow = InstalledAppFlow.from_client_secrets_file(self.s.oauth_client_file, SCOPES)
            creds = flow.run_local_server(port=0)
        os.makedirs(os.path.dirname(token_path), exist_ok=True)
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        return creds

    def connect(self) -> None:
        import gspread
        if not self.s.spreadsheet_id:
            raise SheetError("No spreadsheet_id set in settings.json.")
        try:
            # BackOffHTTPClient waits and retries when Google's per-minute limit is hit.
            client = gspread.authorize(self._credentials(),
                                       http_client=gspread.http_client.BackOffHTTPClient)
            book = client.open_by_key(self.s.spreadsheet_id)
            self.ws = book.worksheet(self.s.worksheet_name)
            self.title = book.title
        except gspread.exceptions.SpreadsheetNotFound:
            raise SheetError("Spreadsheet not found, or this Google account has no access to it.")
        except gspread.exceptions.WorksheetNotFound:
            raise SheetError(f"The sheet has no tab named '{self.s.worksheet_name}'.")
        except SheetError:
            raise
        except Exception as e:
            raise SheetError(f"Could not connect to Google Sheets: {e}")

    @property
    def connected(self) -> bool:
        return self.ws is not None

    # ── Reading ──────────────────────────────────────────────────────────

    def snapshot(self) -> Snapshot:
        """One API call: read the columns we need for duplicate and free-row checks."""
        keys = sorted(set(["invoice", "code", "net"] + list(self.s.empty_row_check)))
        keys = [k for k in keys if k in self.cols]
        ranges = [f"{self.cols[k]}:{self.cols[k]}" for k in keys]
        result = self.ws.batch_get(ranges, major_dimension="COLUMNS")
        data = {}
        for k, vr in zip(keys, result):
            col = list(vr[0]) if vr and len(vr) else []
            data[k] = col

        height = max((len(c) for c in data.values()), default=0)
        cell = lambda k, i: (str(data[k][i]).strip() if i < len(data.get(k, [])) else "")

        first = self.s.header_rows  # 0-based index of first data row
        next_empty = None
        by_inv: dict = {}
        for i in range(first, height):
            inv = cell("invoice", i)
            if inv:
                key = invoice_key(inv, self.s.invoice_prefix)
                by_inv.setdefault(key, []).append((i + 1, cell("code", i).upper(), cell("net", i)))
            if next_empty is None and all(not cell(k, i) for k in self.s.empty_row_check if k in data):
                next_empty = i + 1
        if next_empty is None:
            next_empty = max(height, first) + 1
        return Snapshot(next_empty_row=next_empty, rows_by_invoice=by_inv, prefix=self.s.invoice_prefix)

    # ── Writing ──────────────────────────────────────────────────────────

    def time_only(self) -> bool:
        """
        Should the timestamp column get just the time (8:21:14 AM) or date + time?
        "auto" copies whatever the rows already in the sheet use, so formulas such as
        Diff (RACK 1 timestamp − BILL ENTRY timestamp) keep working.
        """
        mode = self.s.timestamp_format
        if mode in ("time", "datetime"):
            return mode == "time"
        if self._time_only is None:
            self._time_only = True  # the sheet shows times only
            col = self.cols.get("timestamp")
            if col:
                try:
                    vr = self.ws.batch_get([f"{col}{self.s.header_rows + 1}:{col}"],
                                           value_render_option="UNFORMATTED_VALUE")
                    nums = [v[0] for v in (vr[0] if vr else []) if v and isinstance(v[0], (int, float))]
                    if nums:
                        self._time_only = nums[-1] < 1  # a time-only value is a fraction of a day
                except Exception:
                    pass
        return self._time_only

    def _invoice_cell(self, inv_no: str):
        if self.s.sheet_invoice_with_prefix:
            return inv_no
        digits = invoice_key(inv_no, self.s.invoice_prefix)
        return int(digits) if digits.isdigit() else digits

    def _row_values(self, bill: dict, timestamp: str) -> dict:
        try:
            net = float(bill["net"])
        except (TypeError, ValueError):
            raise SheetError(f"Amount '{bill.get('net')}' is not a number")
        if self.time_only() and " " in timestamp:
            timestamp = timestamp.split(" ", 1)[1]
        values = {
            "invoice": self._invoice_cell(bill["inv_no"]),
            "code": bill["code"],
            "net": net,                      # written as a real number
            "name": bill.get("name", ""),
            "date": bill.get("date", ""),
            "timestamp": timestamp,
            "machine": self.machine,
        }
        return {k: v for k, v in values.items() if k in self.cols}

    def _write_row(self, row: int, values: dict) -> None:
        if row <= self.s.header_rows:
            raise SheetError(f"Refusing to write into header row {row}")
        updates = [{"range": f"{self.cols[k]}{row}", "values": [[v]]} for k, v in values.items()]
        self.ws.batch_update(updates, value_input_option="USER_ENTERED")

    def _row_matches(self, row: int, values: dict) -> bool:
        keys = [k for k in ("invoice", "code", "machine") if k in values]
        got = self.ws.batch_get([f"{self.cols[k]}{row}" for k in keys])
        for k, vr in zip(keys, got):
            cell = str(vr[0][0]).strip() if vr and vr[0] else ""
            want = str(values[k]).strip()
            if k == "invoice":
                cell, want = invoice_key(cell, self.s.invoice_prefix), invoice_key(want, self.s.invoice_prefix)
            if cell.upper() != want.upper():
                return False
        return True

    def write_bill(self, bill: dict, timestamp: str, attempts: int = 4) -> int:
        """Write the bill to the first free row. Returns the row number used."""
        values = self._row_values(bill, timestamp)
        for attempt in range(attempts):
            row = self.snapshot().next_empty_row
            self._write_row(row, values)
            self.sleep(0.8 + random.random() * 0.6)  # let a simultaneous writer land
            if self._row_matches(row, values):
                return row
            # Another machine took this row — try the next free one.
            self.sleep(random.random())
        raise SheetError("Could not get a free row (the sheet is very busy). Try again.")

    def highlight(self, rows: list[int], color=(1.0, 0.8, 0.8)) -> None:
        width = max(col_to_index(c) for c in self.cols.values())
        reqs = [{
            "repeatCell": {
                "range": {"sheetId": self.ws.id, "startRowIndex": r - 1, "endRowIndex": r,
                          "startColumnIndex": 0, "endColumnIndex": width},
                "cell": {"userEnteredFormat": {"backgroundColor": {
                    "red": color[0], "green": color[1], "blue": color[2]}}},
                "fields": "userEnteredFormat.backgroundColor",
            }
        } for r in rows]
        if reqs:
            self.ws.spreadsheet.batch_update({"requests": reqs})

    def undo(self, row: int, invoice: str) -> None:
        """Clear the cells we wrote in `row`, only if it still holds `invoice`."""
        got = self.ws.batch_get([f"{self.cols['invoice']}{row}"])
        cell = str(got[0][0][0]).strip() if got and got[0] and got[0][0] else ""
        if row <= self.s.header_rows or invoice_key(cell, self.s.invoice_prefix) != invoice_key(invoice, self.s.invoice_prefix):
            raise SheetError(f"Row {row} no longer contains {invoice} — not undoing.")
        self.ws.batch_clear([f"{c}{row}" for c in self.cols.values()])
