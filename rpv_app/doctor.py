"""
Health check: `python -m rpv_app --doctor` (run.bat option 7).

Checks everything the app needs and prints one line per check with what to do about it,
so a problem on a PC can be found without guessing.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys

from . import __version__

OK, WARN, FAIL = "OK  ", "WARN", "FAIL"


def _line(status: str, what: str, detail: str = "") -> str:
    text = f"[{status}] {what}"
    if detail:
        text += f"\n         {detail}"
    print(text)
    return status


def run(connect_to_google: bool = True) -> int:
    from .config import (CALIBRATION_FILE, PENDING_FILE, SETTINGS_FILE, load_calibration,
                         load_party_codes, load_settings, tesseract_path)

    print(f"\n=== RPV Bill Capture {__version__} — health check ===\n")
    results = []

    v = sys.version_info
    results.append(_line(OK if v >= (3, 9) else FAIL, f"Python {v.major}.{v.minor}.{v.micro}",
                         "" if v >= (3, 9) else "Install Python 3.12 (README 3.2)."))

    missing = []
    for mod in ("PIL", "pytesseract", "gspread", "google.oauth2", "google_auth_oauthlib"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    results.append(_line(FAIL if missing else OK, "Python packages",
                         f"Missing: {', '.join(missing)} — run setup_windows.bat again." if missing else ""))

    # Settings
    settings = None
    if not os.path.exists(SETTINGS_FILE):
        results.append(_line(FAIL, "settings.json", "Not found — run setup_windows.bat (or --setup)."))
    try:
        settings = load_settings()
        if os.path.exists(SETTINGS_FILE):
            results.append(_line(OK, "settings.json"))
    except Exception as e:
        results.append(_line(FAIL, "settings.json", str(e)))
    if settings:
        results.append(_line(OK if settings.spreadsheet_id else FAIL, "Google Sheet link",
                             "" if settings.spreadsheet_id else "Not set — run --setup and paste the sheet link."))
        results.append(_line(OK, f"Computer name: {settings.machine_name or '(Windows computer name)'}"))

    # Tesseract
    path = tesseract_path(settings) if settings else None
    if path:
        try:
            out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10)
            ver = (out.stdout or out.stderr).splitlines()[0]
            results.append(_line(OK, f"Tesseract: {ver}", path))
        except Exception as e:
            results.append(_line(FAIL, "Tesseract found but did not run", f"{path}: {e}"))
    else:
        results.append(_line(FAIL, "Tesseract OCR", "Not found — install it (README 3.1)."))

    # Google login files
    client_file = settings.oauth_client_file if settings else ""
    if client_file and os.path.exists(client_file):
        results.append(_line(OK, "Google client_secret.json"))
    else:
        results.append(_line(FAIL, "Google client_secret.json",
                             f"Missing: {client_file or 'credentials/client_secret.json'} (README 2 and 3.4)."))
    from .sheet import default_token_path
    token = (settings.oauth_token_file if settings else "") or default_token_path()
    results.append(_line(OK if os.path.exists(token) else WARN, "Google login on this PC",
                         "" if os.path.exists(token) else "Not logged in yet — run option 5 once."))

    # Google connection
    if connect_to_google and settings and settings.spreadsheet_id and os.path.exists(token):
        from .sheet import SheetClient
        sheet = SheetClient(settings)
        try:
            sheet.connect(interactive=False)
            snap = sheet.snapshot()
            results.append(_line(OK, f"Google Sheet '{sheet.title}' → tab '{settings.worksheet_name}'",
                                 f"next free row {snap.next_empty_row}; writing as '{sheet.machine}'"))
        except Exception as e:
            results.append(_line(FAIL, "Google Sheet connection", str(e)))

    # Calibration
    cal = load_calibration()
    if not cal or "regions" not in cal:
        results.append(_line(FAIL, "Calibration", "Not done — run option 2 with a bill open in RPV."))
    else:
        detail = f"mode '{cal.get('mode')}', made {cal.get('created', '?')}"
        try:
            from .capture import screenshot
            size = list(screenshot().size)
            if cal.get("screen_size") and size != list(cal["screen_size"]):
                results.append(_line(FAIL, "Calibration",
                                     f"Screen is now {size[0]}×{size[1]} but calibration was made at "
                                     f"{cal['screen_size'][0]}×{cal['screen_size'][1]} — calibrate again."))
            else:
                results.append(_line(OK, "Calibration", detail))
        except Exception:
            results.append(_line(OK, "Calibration", detail + " (screen size not checked)"))

    # Extras
    codes = load_party_codes(settings) if settings else {}
    results.append(_line(OK, f"Party code list: {len(codes)} codes" if codes
                         else "Party code list: none (codes only checked for format)"))
    if os.path.exists(PENDING_FILE):
        from .store import PendingQueue
        n = len(PendingQueue(PENDING_FILE))
        if n:
            results.append(_line(WARN, f"{n} bill(s) waiting to upload", "Run option 6 when online."))

    from . import qol
    latest = qol.latest_version() if (settings is None or settings.check_for_updates) else None
    if qol.newer_version_available(latest):
        results.append(_line(WARN, f"Version {latest} is available (this is {__version__})", "Run update.bat."))

    fails, warns = results.count(FAIL), results.count(WARN)
    print()
    if fails:
        print(f"{fails} problem(s) to fix (FAIL), {warns} warning(s).")
    elif warns:
        print(f"Everything needed is in place. {warns} warning(s).")
    else:
        print("Everything is in place.")
    print(f"System: {platform.system()} {platform.release()}")
    return 1 if fails else 0
