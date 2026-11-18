"""
Small conveniences around the capture window: a global hotkey, sounds, remembering the
window position, a single-instance guard, old-log cleanup and the "new version" check.

Everything here fails quietly: a convenience must never stop a clerk from working.
"""

from __future__ import annotations

import json
import os
import platform
import re
import socket
import subprocess
import threading
import time
import urllib.request
import webbrowser
from typing import Optional

from . import __version__
from .config import LOGS_DIR, UI_STATE_FILE, UPDATE_REPO

IS_WINDOWS = platform.system() == "Windows"


# ─── Global hotkey (Windows) ─────────────────────────────────────────────────

_VK = {f"F{i}": 0x6F + i for i in range(1, 13)}  # F1 = 0x70 … F12 = 0x7B
_MODS = {"ALT": 0x1, "CTRL": 0x2, "CONTROL": 0x2, "SHIFT": 0x4}
_MOD_NOREPEAT = 0x4000


def parse_hotkey(text: str) -> Optional[tuple[int, int]]:
    """'F9' → (0, 0x78); 'Ctrl+Shift+F2' → (6, 0x71). Returns None if not understood."""
    if not text or not text.strip():
        return None
    parts = [p.strip().upper() for p in text.split("+") if p.strip()]
    *mods, key = parts
    if key not in _VK or any(m not in _MODS for m in mods):
        return None
    mask = 0
    for m in mods:
        mask |= _MODS[m]
    return mask, _VK[key]


class GlobalHotkey:
    """
    Registers a system-wide hotkey with the Windows RegisterHotKey API (no extra packages).
    The listener runs on its own thread; the Tk window polls `pressed()` so all UI work
    stays on the UI thread.
    """

    def __init__(self, text: str):
        self.text = text
        self.ok = False
        self.error = ""
        self._hits = 0
        self._lock = threading.Lock()
        self._thread_id = None
        parsed = parse_hotkey(text)
        if not text:
            return
        if not parsed:
            self.error = f"Hotkey '{text}' not understood (use e.g. F9 or Ctrl+F9)"
            return
        if not IS_WINDOWS:
            self.error = "Hotkey works on Windows only"
            return
        ready = threading.Event()
        threading.Thread(target=self._run, args=(parsed, ready), daemon=True).start()
        ready.wait(2)

    def _run(self, parsed, ready):
        import ctypes
        from ctypes import wintypes
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()
        mods, vk = parsed
        if not user32.RegisterHotKey(None, 1, mods | _MOD_NOREPEAT, vk):
            self.error = f"{self.text} is already used by another program"
            ready.set()
            return
        self.ok = True
        ready.set()
        msg = wintypes.MSG()
        WM_HOTKEY = 0x0312
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                with self._lock:
                    self._hits += 1
        user32.UnregisterHotKey(None, 1)

    def pressed(self) -> bool:
        with self._lock:
            hit, self._hits = self._hits > 0, 0
        return hit

    def stop(self):
        if IS_WINDOWS and self._thread_id:
            import ctypes
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)  # WM_QUIT


# ─── Sounds ──────────────────────────────────────────────────────────────────

def beep(kind: str, enabled: bool = True, tk_root=None) -> None:
    """kind: 'ok' (saved), 'check' (please look), 'error'."""
    if not enabled:
        return
    try:
        if IS_WINDOWS:
            import winsound
            flag = {"ok": winsound.MB_OK, "check": winsound.MB_ICONASTERISK,
                    "error": winsound.MB_ICONHAND}.get(kind, winsound.MB_OK)
            winsound.MessageBeep(flag)
        elif kind != "ok" and tk_root is not None:
            tk_root.bell()
    except Exception:
        pass


# ─── Window position ─────────────────────────────────────────────────────────

def load_ui_state(path: str = UI_STATE_FILE) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_ui_state(data: dict, path: str = UI_STATE_FILE) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        state = load_ui_state(path)
        state.update(data)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception:
        pass


def position_on_screen(x: int, y: int, screen_w: int, screen_h: int, margin: int = 60) -> bool:
    """True if a window placed at (x, y) would still be reachable on this screen."""
    return -margin < x < screen_w - margin and 0 <= y < screen_h - margin


# ─── Single instance ─────────────────────────────────────────────────────────

class SingleInstance:
    """Holds a local port while the capture window is open; a second copy can't take it."""

    PORT = 47613

    def __init__(self, port: int = PORT):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if IS_WINDOWS:
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            self.sock.bind(("127.0.0.1", port))
            self.sock.listen(1)
            self.ok = True
        except OSError:
            self.ok = False
            self.sock.close()

    def release(self):
        try:
            self.sock.close()
        except Exception:
            pass


# ─── Old log cleanup ─────────────────────────────────────────────────────────

def cleanup_logs(days: int, folder: str = LOGS_DIR, now: Optional[float] = None) -> int:
    """Delete audit logs and crop images older than `days`. Never touches the upload queue."""
    if not days or days <= 0 or not os.path.isdir(folder):
        return 0
    cutoff = (now or time.time()) - days * 86400
    removed = 0
    targets = [os.path.join(folder, f) for f in os.listdir(folder)
               if f.startswith("audit-") and f.endswith(".jsonl")]
    crops = os.path.join(folder, "crops")
    if os.path.isdir(crops):
        targets += [os.path.join(crops, f) for f in os.listdir(crops) if f.endswith(".png")]
    for path in targets:
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
                removed += 1
        except OSError:
            pass
    return removed


# ─── New version check ───────────────────────────────────────────────────────

def _version_tuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def latest_version(timeout: float = 5) -> Optional[str]:
    """The version on GitHub's main branch, or None if it can't be fetched. Sends no data."""
    url = f"https://raw.githubusercontent.com/{UPDATE_REPO}/main/rpv_app/__init__.py"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "rpv-bill-capture"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            text = r.read(4096).decode("utf-8", "replace")
        m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
        return m.group(1) if m else None
    except Exception:
        return None


def newer_version_available(latest: Optional[str], current: str = __version__) -> bool:
    return bool(latest) and _version_tuple(latest) > _version_tuple(current)


class UpdateChecker:
    """Checks in the background; the UI reads `.result` later."""

    def __init__(self, enabled: bool = True):
        self.result: Optional[str] = None
        self.done = not enabled
        if enabled:
            threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        latest = latest_version()
        self.result = latest if newer_version_available(latest) else None
        self.done = True


# ─── Opening things ──────────────────────────────────────────────────────────

def open_folder(path: str) -> None:
    os.makedirs(path, exist_ok=True)
    if IS_WINDOWS:
        os.startfile(path)  # type: ignore[attr-defined]
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def open_sheet(spreadsheet_id: str) -> None:
    if spreadsheet_id:
        webbrowser.open(f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit")
