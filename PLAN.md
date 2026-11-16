# RPV Bill OCR — Debug & Refactor Plan

Goal: a reliable Windows app that reads Code / Net / InvNo from the RPV Viewer and writes correct,
de-duplicated rows to the Google Sheet, with no wrong numbers slipping through silently.

**Decisions:** screen capture only (no PDFs) · net = NETAmount (Bill Amount − SRCNAmt) · manual capture (clerk clicks Next, then Capture) · Windows only · no party-code list yet (codes checked for format only) · no extra test data needed · sheet = Bill no (A, no "L"), Party code (B), Amount (C), BILL ENTRY timestamp (G), machine (Q); rack columns never touched.

---

## Phase 0 — Safety net ✅
- [x] `git init`; original code committed as the first snapshot; `.gitignore` keeps out secrets and customer data.
- [x] Dead files removed (`__pycache__` of deleted modules); real RPV crops moved to `tests/data/`, old PDF-flow log to `legacy/`.
- [ ] **YOU:** replace the Google login — step by step in README.md → "Google setup".

## Phase 1 — Workflow ✅
- [x] Manual capture.

## Phase 2 — Restructure ✅
- [x] New `rpv_app/` package (see README → For developers). Old modules removed (still in git history).
- [x] Dependencies cut to 5 (OpenCV, numpy and pyautogui are no longer needed).

## Phase 3 — Correctness fixes ✅
- [x] Strict validation of invoice, amount and code before anything is written.
- [x] Invoice "L" fix is now length-aware; it no longer eats a digit.
- [x] Confidence = the worst word in each field (not an average that hides bad words). Stricter limit for amounts.
- [x] Amount written as a real number.
- [x] Duplicates: the clerk is asked first (sheet + upload queue + this session); red highlight is kept only when the clerk saves anyway.
- [x] Multi-machine row clash: write → read back → move to next row if another machine took it.
- [x] Column map is configurable in `settings.json`.
- [x] Audit log with crop images restored.
- [x] OCR scale is now automatic (the old fixed 3× upscale got 12/19 right; now 19/19).

## Phase 4 — Tests ✅ (needs more data)
- [x] 55 unit tests (parsing, settings, sheet logic with a fake sheet, offline queue, undo, duplicates).
- [x] Accuracy check: `python -m rpv_app --accuracy tests/data/header_crops` → **19/19 correct, 0 silent errors**.
- [x] Not needed (decided). The first real check is option 3 "Test reading" on the Windows computer.

## Phase 5 — Robustness ✅
- [x] Refuses to read if screen size or scaling changed since calibration.
- [x] Windows DPI-scaling fix (screenshot and calibration use the same real pixels).
- [x] Offline / failed writes go to a local queue and upload later, without double-writing.
- [x] Undo last write; session counts; warning on close if bills are still waiting.
- [x] Google access cut to Sheets only (was full Drive).
- [x] Calibration shows what it read before saving.

## Phase 5b — New RPV bill layout (from the real RPV PDF, Nov 2026) ✅
- [x] Clerks capture from the screen only. The PDF reader is kept as a developer tool for exact test answers (not in run.bat).
- [x] Screen OCR adapted to this layout (party line "(AP37)", Bill Amount, InvNo): 8/8 correct on rendered pages, 0 silent errors, 7/8 accepted without the clerk.
- [x] Second independent reading confirms low-confidence values instead of bothering the clerk.

## Phase 6 — Packaging
- [x] `setup_windows.bat` / `run.bat` rewritten (version check, offline packages, clearer menu).
- [x] Public GitHub repo: install = download ZIP; `update.bat` pulls new versions; setup asks for the Sheet link and the PC name.
- [ ] Single `.exe` installer (PyInstaller), if wanted.

## Phase 7 — Ship
- [ ] Test on the real Windows computer with RPV: Calibrate → Test reading → Practice mode → live.
- [ ] Run one real day's batch next to manual entry and compare.

---

## Waiting on you
1. **New Google login:** follow README.md → "Google setup" when you're ready.
2. **Each computer:** set `"machine_name"` in its `settings.json`, then calibrate (pick what the RPV screen shows).
3. Later, optional: a party code list as `party_codes.csv` (`code,name`, codes like `AP37`).
