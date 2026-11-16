"""Tkinter windows: the small always-on-top capture window and the review dialog."""

from __future__ import annotations

import time
import tkinter as tk
from tkinter import messagebox
from typing import Optional

from PIL import ImageTk

from .bill import Bill, revalidate
from .capture import ScreenChanged
from .session import Session

GREEN, RED, ORANGE, BLUE, GREY = "#2e7d32", "#c62828", "#e65100", "#0052cc", "#555"


class ReviewDialog:
    """Shows the crop next to editable values. Returns the bill, or None if skipped."""

    def __init__(self, parent: tk.Tk, bill: Bill, session: Session):
        self.bill, self.session, self.result = bill, session, None
        self.win = w = tk.Toplevel(parent)
        w.title("Please check this bill")
        w.attributes("-topmost", True)
        w.resizable(False, False)

        tk.Label(w, text="Please check this bill against the screen",
                 font=("Arial", 12, "bold"), fg=RED).pack(pady=(10, 4), padx=12)

        self._photos = []
        for name, img in bill.images.items():
            scale = min(1.0, 520 / max(img.width, 1), 160 / max(img.height, 1))
            shown = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
            photo = ImageTk.PhotoImage(shown)
            self._photos.append(photo)
            tk.Label(w, image=photo, relief="solid", bd=1).pack(padx=12, pady=2)

        if bill.issues:
            tk.Label(w, text="\n".join("• " + i for i in bill.issues), justify="left",
                     fg=RED, font=("Arial", 9), wraplength=520).pack(padx=12, pady=4, anchor="w")

        form = tk.Frame(w)
        form.pack(padx=12, pady=6)
        self.vars = {}
        for r, (key, label) in enumerate((("code", "Party code"), ("net", "Net amount"),
                                          ("inv_no", "Invoice no."))):
            tk.Label(form, text=label + ":", font=("Arial", 11)).grid(row=r, column=0, sticky="e", padx=4, pady=3)
            var = tk.StringVar(value=getattr(bill, key))
            entry = tk.Entry(form, textvariable=var, font=("Consolas", 13), width=18)
            entry.grid(row=r, column=1, pady=3)
            self.vars[key] = var
            if r == 0:
                entry.focus_set()
                entry.select_range(0, "end")

        self.error = tk.Label(w, text="", fg=RED, font=("Arial", 9, "bold"), wraplength=520)
        self.error.pack()

        btns = tk.Frame(w)
        btns.pack(pady=10)
        tk.Button(btns, text="Save  (Enter)", width=14, font=("Arial", 10, "bold"),
                  bg="#4CAF50", command=self.on_save).pack(side="left", padx=6)
        tk.Button(btns, text="Skip  (Esc)", width=12, command=self.on_skip).pack(side="left", padx=6)
        w.bind("<Return>", lambda e: self.on_save())
        w.bind("<Escape>", lambda e: self.on_skip())
        w.protocol("WM_DELETE_WINDOW", self.on_skip)

        w.update_idletasks()
        x = parent.winfo_rootx() + 30
        y = parent.winfo_rooty() + 30
        w.geometry(f"+{x}+{y}")
        w.grab_set()
        parent.wait_window(w)

    def on_save(self):
        typed = {k: v.get() for k, v in self.vars.items()}
        clean, blocking = revalidate(typed, self.session.settings, self.session.party_codes)
        if blocking:
            self.error.config(text="Can't save yet: " + "; ".join(blocking))
            return
        changed = any(clean[k] != getattr(self.bill, k) for k in ("code", "net", "inv_no"))
        for k in ("code", "net", "inv_no", "name"):
            setattr(self.bill, k, clean[k] or getattr(self.bill, k))
        self.bill.user_modified = changed
        self.session.stats.reviewed += 1
        self.result = self.bill
        self.win.destroy()

    def on_skip(self):
        self.result = None
        self.win.destroy()


class CaptureWindow:
    def __init__(self, session: Session, sheet_error: str = ""):
        self.s = session
        self.root = root = tk.Tk()
        root.title("RPV Bill Capture")
        root.attributes("-topmost", True)
        root.resizable(False, False)

        tk.Label(root, text="RPV Bill Capture", font=("Arial", 14, "bold")).pack(pady=(12, 2))
        if session.dry_run:
            mode, color = "TEST MODE — nothing is written to the sheet", ORANGE
        elif session.sheet and session.sheet.connected:
            mode, color = f"Connected to '{session.sheet.title}'", GREEN
        else:
            mode, color = "OFFLINE — bills are kept locally and uploaded later", RED
        tk.Label(root, text=mode, fg=color, font=("Arial", 9, "bold"), wraplength=360).pack()
        if sheet_error:
            tk.Label(root, text=sheet_error, fg=RED, font=("Arial", 8), wraplength=360).pack()

        self.btn = tk.Button(root, text="CAPTURE BILL", font=("Arial", 15, "bold"),
                             bg="#4CAF50", height=2, command=self.on_capture)
        self.btn.pack(fill="x", padx=16, pady=(10, 4))
        tk.Label(root, text="Click Next in RPV, then click Capture.", fg=GREY,
                 font=("Arial", 9)).pack()

        self.status = tk.Label(root, text="Ready.", font=("Arial", 10, "bold"), fg=BLUE,
                               justify="center", wraplength=360)
        self.status.pack(pady=(10, 4), padx=10)
        self.counts = tk.Label(root, text="", font=("Arial", 9), fg=GREY)
        self.counts.pack()

        row = tk.Frame(root)
        row.pack(pady=(6, 12))
        self.undo_btn = tk.Button(row, text="Undo last", command=self.on_undo, state="disabled")
        self.undo_btn.pack(side="left", padx=4)
        self.retry_btn = tk.Button(row, text="Upload waiting", command=self.on_retry)
        self.retry_btn.pack(side="left", padx=4)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.refresh_counts()

    # ── helpers ──────────────────────────────────────────────────────────

    def set_status(self, text: str, color: str = BLUE):
        self.status.config(text=text, fg=color)
        self.root.update_idletasks()

    def refresh_counts(self):
        st = self.s.stats
        waiting = len(self.s.queue)
        self.counts.config(text=f"Saved {st.written} · Skipped {st.skipped} · "
                                f"Checked by you {st.reviewed} · Waiting to upload {waiting}")
        online = bool(self.s.sheet and self.s.sheet.connected)
        self.retry_btn.config(state="normal" if waiting and online else "disabled")
        self.undo_btn.config(state="normal" if self.s.last_written else "disabled")

    # ── actions ──────────────────────────────────────────────────────────

    def on_capture(self):
        self.btn.config(state="disabled")
        try:
            self._capture()
        finally:
            self.btn.config(state="normal")
            self.refresh_counts()

    def _capture(self):
        self.root.withdraw()
        self.root.update()
        time.sleep(0.25)  # let the window disappear before the screenshot
        try:
            from .capture import screenshot
            frame = screenshot()
        finally:
            self.root.deiconify()
            self.root.attributes("-topmost", True)

        self.set_status("Reading…")
        try:
            bill = self.s.read_screen(frame)
        except ScreenChanged as e:
            self.set_status("Screen changed — recalibrate.", RED)
            messagebox.showerror("Recalibrate needed", str(e), parent=self.root)
            return
        except Exception as e:
            self.set_status(f"Could not read the screen: {e}", RED)
            return

        if bill.needs_review:
            reviewed = ReviewDialog(self.root, bill, self.s).result
            if reviewed is None:
                self.s.skip(bill)
                self.set_status(f"Skipped (invoice {bill.inv_no or '?'}).", GREY)
                return
            bill = reviewed

        self.set_status("Checking for duplicates…")
        dups = self.s.find_duplicates(bill.inv_no)
        dups_real = [d for d in dups if not d.startswith("(could not")]
        if dups_real:
            ok = messagebox.askyesno(
                "Duplicate invoice",
                f"Invoice {bill.inv_no} is already recorded:\n\n• " + "\n• ".join(dups_real) +
                "\n\nDid you forget to click Next in RPV?\n\nSave it again anyway?",
                default="no", icon="warning", parent=self.root)
            if not ok:
                self.s.skip(bill, reason="duplicate — not saved")
                self.set_status(f"Not saved: {bill.inv_no} is a duplicate.", ORANGE)
                return

        self.set_status("Saving…")
        result = self.s.save(bill, duplicate_of=dups_real or None)
        color = {"written": GREEN, "dry_run": ORANGE, "queued": RED}[result.status]
        self.set_status(f"{result.message}\n{bill.inv_no}  |  {bill.code}  |  {bill.net}", color)

    def on_undo(self):
        if not self.s.last_written:
            return
        row, inv = self.s.last_written
        if not messagebox.askyesno("Undo", f"Remove {inv} from row {row} of the sheet?", parent=self.root):
            return
        try:
            self.set_status(self.s.undo_last(), GREY)
        except Exception as e:
            self.set_status(f"Undo failed: {e}", RED)
        self.refresh_counts()

    def on_retry(self):
        self.set_status("Uploading waiting bills…")
        done, left, msgs = self.s.retry_pending()
        self.set_status(f"Uploaded {done}, still waiting {left}.", GREEN if not left else ORANGE)
        if msgs:
            messagebox.showinfo("Upload results", "\n".join(msgs), parent=self.root)
        self.refresh_counts()

    def on_close(self):
        waiting = len(self.s.queue)
        if waiting and not messagebox.askyesno(
                "Bills not uploaded",
                f"{waiting} bill(s) are still waiting to upload. They are saved on this computer "
                "and will be offered for upload next time.\n\nClose anyway?", parent=self.root):
            return
        self.root.destroy()

    def run(self):
        if len(self.s.queue) and self.s.sheet and self.s.sheet.connected:
            self.root.after(500, self._offer_retry)
        self.root.mainloop()
        st = self.s.stats
        print(f"\nSession finished: {st.captured} captured, {st.written} saved, "
              f"{st.skipped} skipped, {len(self.s.queue)} waiting to upload.")

    def _offer_retry(self):
        n = len(self.s.queue)
        if messagebox.askyesno("Bills waiting", f"{n} bill(s) from earlier were not uploaded. Upload now?",
                               parent=self.root):
            self.on_retry()


class ImportWindow:
    """
    Developer tool (not shown to clerks): read bills from RPV PDF printouts, show them,
    and optionally save them. Mainly used to get exact values for testing the screen OCR.
    """

    STATUS_TEXT = {"ready": "Ready", "problem": "PROBLEM", "duplicate": "Already recorded",
                   "saved": "Saved", "queued": "Waiting to upload"}

    def __init__(self, session: Session, paths: Optional[list] = None, parent: Optional[tk.Misc] = None):
        from tkinter import filedialog, ttk
        self.s = session
        self.own_root = parent is None
        self.win = w = tk.Tk() if parent is None else tk.Toplevel(parent)
        w.title("Import bills from PDF")
        if not paths:
            paths = list(filedialog.askopenfilenames(
                parent=w, title="Choose the PDF printed from RPV",
                filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")]))
        if not paths:
            w.destroy()
            self.items = []
            return

        self.items = self._read(paths)

        top = tk.Frame(w)
        top.pack(fill="x", padx=10, pady=(10, 4))
        names = ", ".join(p.split("/")[-1].split("\\")[-1] for p in paths)
        tk.Label(top, text=f"From: {names}", font=("Arial", 10, "bold")).pack(anchor="w")
        if session.dry_run:
            tk.Label(top, text="TEST MODE — nothing is written to the sheet", fg=ORANGE,
                     font=("Arial", 9, "bold")).pack(anchor="w")
        elif not (session.sheet and session.sheet.connected):
            tk.Label(top, text="OFFLINE — bills will be kept locally and uploaded later", fg=RED,
                     font=("Arial", 9, "bold")).pack(anchor="w")

        cols = ("invoice", "code", "party", "date", "amount", "status")
        self.tree = t = ttk.Treeview(w, columns=cols, show="headings", height=min(max(len(self.items), 4), 18))
        for c, label, width, anchor in (("invoice", "Invoice", 80, "w"), ("code", "Code", 60, "w"),
                                        ("party", "Party", 250, "w"), ("date", "Date", 95, "w"),
                                        ("amount", "Net amount", 95, "e"), ("status", "Status", 140, "w")):
            t.heading(c, text=label)
            t.column(c, width=width, anchor=anchor)
        t.tag_configure("problem", foreground=RED)
        t.tag_configure("duplicate", foreground=ORANGE)
        t.tag_configure("saved", foreground=GREEN)
        t.tag_configure("queued", foreground=RED)
        t.pack(fill="both", expand=True, padx=10)
        t.bind("<<TreeviewSelect>>", self.on_select)

        self.detail = tk.Label(w, text="Click a bill to see its checks.", fg=GREY, justify="left",
                               wraplength=740, font=("Arial", 9))
        self.detail.pack(fill="x", padx=10, pady=4)

        bar = tk.Frame(w)
        bar.pack(pady=(4, 10))
        self.save_btn = tk.Button(bar, font=("Arial", 11, "bold"), bg="#4CAF50", command=self.on_save)
        self.save_btn.pack(side="left", padx=6)
        tk.Button(bar, text="Close", width=10, command=w.destroy).pack(side="left", padx=6)
        self.summary = tk.Label(w, text="", font=("Arial", 9))
        self.summary.pack(pady=(0, 8))
        self.refresh()

        if parent is not None:
            w.transient(parent)
            w.grab_set()
            parent.wait_window(w)
        else:
            w.mainloop()

    def _read(self, paths):
        from .pdf_import import read_pdf
        bills = []
        for p in paths:
            try:
                bills += read_pdf(p, self.s.settings, self.s.party_codes)
            except Exception as e:
                messagebox.showerror("Could not read PDF", f"{p}\n\n{e}", parent=self.win)
        return self.s.check_import(bills)

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for i, it in enumerate(self.items):
            b = it["pdf"].bill
            self.tree.insert("", "end", iid=str(i), tags=(it["status"],), values=(
                b.inv_no, b.code, b.name, b.date, b.net, self.STATUS_TEXT[it["status"]]))
        counts = {k: sum(1 for it in self.items if it["status"] == k) for k in self.STATUS_TEXT}
        n_ready = counts["ready"]
        self.save_btn.config(text=f"Save {n_ready} ready bill(s)" if n_ready else "Nothing to save",
                             state="normal" if n_ready else "disabled")
        self.summary.config(text=f"{len(self.items)} bills · ready {counts['ready']} · saved {counts['saved']} · "
                                 f"already recorded {counts['duplicate']} · problems {counts['problem']} · "
                                 f"waiting to upload {counts['queued']}")

    def on_select(self, _e=None):
        sel = self.tree.selection()
        if not sel:
            return
        it = self.items[int(sel[0])]
        pb = it["pdf"]
        lines = [f"{pb.bill.inv_no} — PDF page(s) {', '.join(map(str, pb.pages))}: {it['detail']}"]
        if pb.checks:
            lines.append("Checks passed: " + "; ".join(pb.checks))
        self.detail.config(text="\n".join(lines), fg=RED if it["status"] == "problem" else GREY)

    def on_save(self):
        n = sum(1 for it in self.items if it["status"] == "ready")
        target = "test mode (not written)" if self.s.dry_run else "the sheet"
        if not messagebox.askyesno("Save bills", f"Save {n} bill(s) to {target}?", parent=self.win):
            return
        self.save_btn.config(state="disabled")

        def progress(i, total):
            self.summary.config(text=f"Saving {i} of {total}…")
            self.win.update()

        self.s.save_import(self.items, progress)
        self.refresh()
        problems = sum(1 for it in self.items if it["status"] in ("problem", "duplicate"))
        if problems:
            messagebox.showinfo("Done", f"{problems} bill(s) were not saved — they are shown in red/orange. "
                                        "Enter those by hand after checking them.", parent=self.win)
