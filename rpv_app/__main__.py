"""
RPV Bill OCR — command line entry point.

    python -m rpv_app                  open the capture window
    python -m rpv_app --dry-run        capture without writing to the sheet
    python -m rpv_app --calibrate      draw the boxes around the RPV fields
    python -m rpv_app --test           read the current RPV screen once and print the result
    python -m rpv_app --test-sheets    check the Google Sheets connection
    python -m rpv_app --upload         upload bills waiting in the offline queue
    python -m rpv_app --setup          ask for the Google Sheet link and this computer's name
    python -m rpv_app --doctor         check everything (Python, Tesseract, settings, Google, calibration)
    python -m rpv_app --accuracy DIR   measure OCR accuracy on saved crops (see accuracy.py)
Developer tools (not in run.bat — clerks capture from the screen):
    python -m rpv_app --pdf-check FILE print the exact bill values in an RPV PDF (for test data)
    python -m rpv_app --pdf [FILE..]   import bills from an RPV PDF (opens a window)
"""

from __future__ import annotations

import argparse
import sys
import time

from . import __version__


def _fail(msg: str, popup: bool = False) -> int:
    print(f"\nERROR: {msg}\n")
    if popup:  # the capture window may be started without a visible console
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("RPV Bill Capture", msg.replace("       ", ""))
            root.destroy()
        except Exception:
            pass
    return 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="rpv_app", description="RPV Bill OCR → Google Sheets")
    p.add_argument("--dry-run", action="store_true", help="capture without writing to the sheet")
    p.add_argument("--calibrate", action="store_true", help="draw the boxes around the RPV fields")
    p.add_argument("--test", action="store_true", help="read the current screen once and print it")
    p.add_argument("--test-sheets", action="store_true", help="check the Google Sheets connection")
    p.add_argument("--upload", action="store_true", help="upload bills waiting in the offline queue")
    p.add_argument("--accuracy", metavar="DIR", help="measure OCR accuracy on saved crops")
    p.add_argument("--pdf", nargs="*", metavar="FILE", help="import bills from RPV PDF printouts")
    p.add_argument("--pdf-check", nargs="+", metavar="FILE", help="show what a PDF contains, write nothing")
    p.add_argument("--setup", action="store_true", help="ask for the sheet link and this computer's name")
    p.add_argument("--doctor", action="store_true", help="check everything and print what's wrong")
    p.add_argument("--version", action="version", version=f"RPV Bill OCR {__version__}")
    args = p.parse_args(argv)

    if args.setup:
        return first_setup()
    if args.doctor:
        from .doctor import run as run_doctor
        return run_doctor()

    capture_mode = not any((args.calibrate, args.test, args.test_sheets, args.upload,
                            args.accuracy, args.pdf is not None, args.pdf_check))

    from .config import load_calibration, load_party_codes, load_settings
    try:
        settings = load_settings()
    except Exception as e:
        return _fail(f"settings.json has a problem: {e}", popup=capture_mode)

    from . import ocr
    if args.accuracy:
        from . import accuracy
        return accuracy.run(args.accuracy, settings)

    if args.test_sheets:
        return _test_sheets(settings)

    if args.pdf_check:
        return _pdf_check(settings, args.pdf_check)

    if args.pdf is not None:
        from .session import Session
        from .ui import ImportWindow
        sheet, err = (None, "") if args.dry_run else _connect(settings)
        if err:
            print(f"WARNING: {err}\nContinuing offline — bills will be kept locally and uploaded later.")
        session = Session(settings, calibration={}, sheet=sheet, dry_run=args.dry_run,
                          party_codes=load_party_codes(settings))
        ImportWindow(session, paths=args.pdf)
        return 0

    if args.upload:
        from .session import Session
        sheet, err = _connect(settings)
        if err:
            return _fail(err)
        s = Session(settings, calibration={}, sheet=sheet)
        done, left, msgs = s.retry_pending()
        print("\n".join(msgs) or "Nothing waiting to upload.")
        print(f"Uploaded {done}, still waiting {left}.")
        return 0 if not left else 1

    try:
        ocr.setup_tesseract(settings)
    except ocr.TesseractMissing as e:
        return _fail(str(e), popup=capture_mode)

    if args.calibrate:
        from . import calibrate
        return 0 if calibrate.run(settings) else 1

    calibration = load_calibration()
    if not calibration or "regions" not in calibration:
        return _fail("The screen has not been calibrated yet (or was calibrated with the old version).\n"
                     "       Run Calibrate first (run.bat option 2).", popup=capture_mode)

    party_codes = load_party_codes(settings)
    if not party_codes:
        print("Note: no party_codes.csv found — party codes are only checked for format.")

    if args.test:
        return _test_screen(settings, calibration, party_codes)

    from . import qol
    from .session import Session
    from .ui import CaptureWindow
    lock = qol.SingleInstance()
    if not lock.ok:
        return _fail("RPV Bill Capture is already open on this computer.\n"
                     "       Look for its window (it may be behind RPV).", popup=True)
    removed = qol.cleanup_logs(settings.keep_logs_days)
    if removed:
        print(f"Removed {removed} log file(s) older than {settings.keep_logs_days} days.")
    sheet, err = (None, "") if args.dry_run else _connect(settings)
    if err:
        print(f"WARNING: {err}\nContinuing offline — bills will be kept locally and uploaded later.")
    session = Session(settings, calibration, sheet=sheet, dry_run=args.dry_run, party_codes=party_codes)
    try:
        CaptureWindow(session, sheet_error=err).run()
    finally:
        lock.release()
    return 0


def sheet_id_from(text: str) -> str:
    """Accept a full Google Sheets link or just the ID."""
    import re
    text = text.strip()
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", text)
    if m:
        return m.group(1)
    return text if re.fullmatch(r"[A-Za-z0-9_-]{20,}", text) else ""


def first_setup() -> int:
    """Create or update settings.json by asking two questions."""
    import json
    import os
    import socket
    from .config import SETTINGS_FILE
    data = {}
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

    print("\n=== RPV Bill Capture — settings for this computer ===\n")
    current = data.get("spreadsheet_id", "")
    while True:
        prompt = "Paste the Google Sheet link (open the sheet, copy the address bar)"
        prompt += f"\n  [Enter = keep current]: " if current else ":\n  > "
        answer = input(prompt).strip()
        if not answer and current:
            break
        sid = sheet_id_from(answer)
        if sid:
            data["spreadsheet_id"] = sid
            break
        print("  That doesn't look like a Google Sheets link. Try again.\n")

    default_name = data.get("machine_name") or socket.gethostname()
    name = input(f"\nName for this computer, shown in the sheet's machine column "
                 f"(e.g. Counter 1)\n  [Enter = {default_name}]: ").strip()
    data["machine_name"] = name or default_name

    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\nSaved {SETTINGS_FILE}")
    return 0


def _connect(settings):
    from .sheet import SheetClient
    sheet = SheetClient(settings)
    try:
        sheet.connect()
        return sheet, ""
    except Exception as e:
        return None, str(e)


def _test_sheets(settings) -> int:
    sheet, err = _connect(settings)
    if err:
        return _fail(err)
    snap = sheet.snapshot()
    print(f"Connected to '{sheet.title}' → tab '{settings.worksheet_name}'")
    print(f"Next free row: {snap.next_empty_row}")
    print(f"Invoices already in sheet: {len(snap.rows_by_invoice)}")
    print("Columns written: " + ", ".join(f"{k}={v}" for k, v in sheet.cols.items()))
    print(f"This computer will be recorded as: {sheet.machine}")
    print(f"Timestamp style: {'time only (e.g. 8:21:14 AM)' if sheet.time_only() else 'date and time'}")
    print("Bill numbers are written " + ("with the L (L81678)" if settings.sheet_invoice_with_prefix
                                          else "without the L (81678), like the existing rows"))
    return 0


def _pdf_check(settings, paths) -> int:
    from .pdf_import import read_pdf
    codes = load_party_codes_safe(settings)
    bad = 0
    for path in paths:
        print(f"\n{path}")
        print(f"  {'Invoice':8s} {'Code':6s} {'Date':12s} {'Net':>11s}  Pages   Party")
        for pb in read_pdf(path, settings, codes):
            b = pb.bill
            mark = "OK " if pb.ok else "BAD"
            print(f"{mark} {b.inv_no:8s} {b.code:6s} {b.date:12s} {b.net:>11s}  {','.join(map(str, pb.pages)):6s}  {b.name}")
            for prob in pb.problems:
                print(f"      PROBLEM: {prob}")
            bad += not pb.ok
    print(f"\n{bad} bill(s) with problems." if bad else "\nAll bills passed every check.")
    return 1 if bad else 0


def load_party_codes_safe(settings):
    from .config import load_party_codes
    try:
        return load_party_codes(settings)
    except Exception:
        return {}


def _test_screen(settings, calibration, party_codes) -> int:
    from . import capture
    from .bill import read_bill
    from .store import AuditLog
    print("Reading the screen in 3 seconds — bring RPV Viewer to the front…")
    time.sleep(3)
    frame = capture.screenshot()
    try:
        bill = read_bill(frame, calibration, settings, party_codes)
    except capture.ScreenChanged as e:
        return _fail(str(e))
    print("-" * 50)
    for key, label in (("code", "Code"), ("net", "Net"), ("inv_no", "Invoice")):
        print(f"  {label:8s} {getattr(bill, key):14s} ({bill.confidence.get(key, 0):.0f}% confidence)")
    if bill.name:
        print(f"  Name     {bill.name}")
    print("-" * 50)
    print("Would be sent for checking:\n  • " + "\n  • ".join(bill.issues) if bill.issues
          else "Looks good — would be saved without asking.")
    if bill.notes:
        print("Auto-corrections: " + "; ".join(bill.notes))
    paths = AuditLog().save_images(bill.images)
    print("Crops saved for inspection: " + ", ".join(paths.values()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
