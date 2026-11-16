"""
Calibration: show a screenshot of the RPV Viewer and let the user draw boxes
around the fields to read. Saved to rpv_regions.json.
"""

from __future__ import annotations

import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox

from PIL import ImageTk

from . import capture
from .bill import read_bill
from .config import Settings, load_party_codes, save_calibration

STEPS = {
    "header": [("header", "Draw ONE box around the Code:, Name:, Net : and InvNo : lines (all four, with their labels)")],
    "fields": [
        ("code", "Box the PARTY NAME line with the code in brackets, e.g. SOME PHARMA DISTRIBUTORS(AP37). "
                 "Make it wide enough for the longest party name"),
        ("net", "Box the BILL AMOUNT number at the bottom (e.g. 13546.00) — the number only"),
        ("inv_no", "Box the INVOICE number only, after 'InvNo :' (e.g. L81027)"),
    ],
}


def _ask_mode(root: tk.Tk) -> str | None:
    choice = {"mode": None}
    w = tk.Toplevel(root)
    w.title("Calibration")
    w.attributes("-topmost", True)
    tk.Label(w, text="What does the RPV screen show?", font=("Arial", 12, "bold")).pack(padx=16, pady=(14, 8))

    def pick(m):
        choice["mode"] = m
        w.destroy()

    tk.Button(w, text="Lines like  Code: ABC / Name: ... / Net : 11653.00 / InvNo : L81678\n"
                      "→ draw ONE box around those lines", width=62, justify="left",
              command=lambda: pick("header")).pack(padx=16, pady=4)
    tk.Button(w, text="A printed bill with  PARTY NAME(AP37) ... InvNo : L81027 ... Bill Amount\n"
                      "→ draw THREE boxes", width=62, justify="left",
              command=lambda: pick("fields")).pack(padx=16, pady=4)
    tk.Label(w, text="Open RPV Viewer on a bill first. After you choose,\n"
                     "you have 3 seconds to bring RPV to the front.",
             fg="#555").pack(padx=16, pady=(8, 14))
    w.protocol("WM_DELETE_WINDOW", w.destroy)
    w.grab_set()
    root.wait_window(w)
    return choice["mode"]


class RegionPicker:
    def __init__(self, root: tk.Tk, frame, steps):
        self.frame, self.steps, self.regions = frame, steps, {}
        self.i, self.rect, self.start, self.current = 0, None, None, None
        self.cancelled = False

        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        self.scale = min(sw * 0.9 / frame.width, (sh * 0.85 - 60) / frame.height, 1.0)
        disp = frame.resize((int(frame.width * self.scale), int(frame.height * self.scale)))

        self.win = w = tk.Toplevel(root)
        w.title("Calibration — draw a box")
        w.attributes("-topmost", True)
        self.prompt = tk.Label(w, font=("Arial", 12, "bold"), fg="#c62828")
        self.prompt.pack(pady=4)
        self.photo = ImageTk.PhotoImage(disp)
        self.canvas = tk.Canvas(w, width=disp.width, height=disp.height, cursor="crosshair")
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        self.canvas.pack()
        bar = tk.Frame(w)
        bar.pack(pady=4)
        self.ok_btn = tk.Button(bar, text="OK, next  (Enter)", command=self.accept, state="disabled", width=16)
        self.ok_btn.pack(side="left", padx=4)
        tk.Button(bar, text="Cancel  (Esc)", command=self.cancel, width=12).pack(side="left", padx=4)

        self.canvas.bind("<ButtonPress-1>", self.on_down)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_up)
        w.bind("<Return>", lambda e: self.accept())
        w.bind("<Escape>", lambda e: self.cancel())
        w.protocol("WM_DELETE_WINDOW", self.cancel)
        self.show_step()
        w.grab_set()
        root.wait_window(w)

    def show_step(self):
        self.prompt.config(text=f"Step {self.i + 1}/{len(self.steps)}: {self.steps[self.i][1]}")
        self.ok_btn.config(state="disabled")
        self.current = None

    def on_down(self, e):
        self.start = (e.x, e.y)
        if self.rect:
            self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="red", width=2)

    def on_drag(self, e):
        if self.start:
            self.canvas.coords(self.rect, *self.start, e.x, e.y)

    def on_up(self, e):
        if not self.start:
            return
        x1, y1 = self.start
        x2, y2 = e.x, e.y
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))
        if x2 - x1 < 5 or y2 - y1 < 5:
            return
        s = self.scale
        self.current = {"x1": int(x1 / s), "y1": int(y1 / s), "x2": int(x2 / s), "y2": int(y2 / s)}
        self.ok_btn.config(state="normal")

    def accept(self):
        if not self.current:
            return
        key = self.steps[self.i][0]
        self.regions[key] = self.current
        c = self.current
        s = self.scale
        self.canvas.create_rectangle(c["x1"] * s, c["y1"] * s, c["x2"] * s, c["y2"] * s, outline="green", width=2)
        self.canvas.create_text(c["x1"] * s + 3, c["y1"] * s - 8, text=key, fill="green", anchor="w")
        self.rect = None
        self.i += 1
        if self.i >= len(self.steps):
            self.win.destroy()
        else:
            self.show_step()

    def cancel(self):
        self.cancelled = True
        self.win.destroy()


def run(settings: Settings) -> bool:
    capture.make_dpi_aware()
    root = tk.Tk()
    root.withdraw()
    mode = _ask_mode(root)
    if not mode:
        root.destroy()
        return False

    time.sleep(3)
    frame = capture.screenshot()
    picker = RegionPicker(root, frame, STEPS[mode])
    if picker.cancelled:
        root.destroy()
        print("Calibration cancelled.")
        return False

    data = {
        "mode": mode,
        "regions": picker.regions,
        "screen_size": [frame.width, frame.height],
        "created": datetime.now().isoformat(timespec="seconds"),
    }

    # Read the screenshot right away so the user can see whether the boxes work.
    try:
        from . import ocr
        ocr.setup_tesseract(settings)
        bill = read_bill(frame, data, settings, load_party_codes(settings))
        summary = (f"Code:      {bill.code}\nNet:       {bill.net}\nInvoice:  {bill.inv_no}\n\n" +
                   ("Problems:\n• " + "\n• ".join(bill.issues) if bill.issues else "No problems found."))
    except Exception as e:
        summary = f"Could not read the boxes: {e}"

    keep = messagebox.askyesno("Check calibration",
                               f"This is what was read from the screen:\n\n{summary}\n\n"
                               "Are these values correct? (Yes = save, No = discard and try again)")
    root.destroy()
    if keep:
        save_calibration(data)
        print("Calibration saved.")
        return True
    print("Calibration discarded.")
    return False
