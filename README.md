# RPV Bill Capture

Reads the **party code, net amount and invoice number** (and optionally the party name and bill date)
of RPV bills and writes them to the "Bill Entry" Google Sheet, with checks so a wrong number never goes in silently.

## How it works

1. The clerk clicks **Next** in RPV Viewer, then **CAPTURE BILL** in the small always-on-top window.
2. The app takes a screenshot, crops the calibrated box, and reads it with Tesseract OCR.
3. Every value is checked:
   - Invoice number must be `L` + 5 digits. Known misreads (`161371`, `1L61170`, a missing `L`) are fixed safely.
   - Amount must be a real number with 2 decimals. If letters looked like digits, the clerk must confirm.
   - Party code must look like a code (e.g. `AP37`, taken from the brackets after the party name). If a `party_codes.csv` list is added later, the code must also be on it.
   - When a value was hard to read (low OCR confidence), it is read a second time with different image processing. If both readings agree it is accepted; otherwise it is sent for checking.
   - On page 1 of a multi-page bill there is no Bill Amount, so the app asks the clerk to go to the last page.
4. If anything is doubtful, a **check window** shows the crop next to the values. The clerk fixes them and presses Enter, or presses Esc to skip.
5. If the invoice is already in the sheet, in the upload queue, or was already captured this session, the app asks first. (This usually means Next wasn't clicked.)
6. The bill is written to the first free row (see "How rows are written" below).
7. If Google Sheets can't be reached, the bill is saved on the computer and uploaded later. Nothing is lost.
8. Every capture is logged in `logs/audit-<date>.jsonl`, with the crop images in `logs/crops/`.

## Setup on a Windows computer

Follow [INSTALL_WINDOWS.md](INSTALL_WINDOWS.md). In short:
1. Install Tesseract and Python 3.12.
2. Download the ZIP from GitHub.
3. Add `credentials\client_secret.json`.
4. Run `setup_windows.bat`. It asks for the Sheet link and this computer's name.
5. Run `run.bat`.

To get new versions, double-click `update.bat`.

The first time Google Sheets is used, a browser opens to log in. The login is stored for this
Windows user in `%APPDATA%\RPVBillOCR\token.json`, not in the app folder.

## Google setup

The app logs in to Google with an "OAuth client" file, `credentials\client_secret.json`.
These steps replace the old client, whose secret and login token were copied around, with a new one.
You need the Google account that owns the Google Cloud project.

### 1. Revoke the old access
1. Sign in to https://myaccount.google.com/permissions with each Google account that used the old tool.
   Under third-party apps, find this app and choose **Remove access**. Old `token.json` files then stop working.
2. Open https://console.cloud.google.com and pick the project. Its ID is the `project_id` in the old
   `client_secret.json`. Go to **APIs & Services → Credentials**. Under **OAuth 2.0 Client IDs**, delete the old client.

### 2. Create the new client
3. In the same project, go to **APIs & Services → Library**, open **Google Sheets API**, and make sure it is **Enabled**.
   (Google Drive API is no longer needed.)
4. Go to **APIs & Services → Credentials → Create credentials → OAuth client ID**.
   Choose **Desktop app** as the application type, name it `RPV Bill Capture`, click **Create**, then **Download JSON**.
5. Rename the downloaded file to `client_secret.json`. Each PC needs a copy in its `credentials` folder.
   **Never put it on GitHub.** The repo is public, and the file is excluded by `.gitignore`.

### 3. Stop the weekly re-login
6. Go to **Google Auth Platform → Audience** (older consoles call it the "OAuth consent screen"):
   - If you use a company Google Workspace account, set the user type to **Internal**. Nothing else is needed.
   - Otherwise it is **External**. If the publishing status is **Testing**, Google logs everyone out after
     **7 days**. Click **Publish app** to fix this. You don't need Google verification for your own use. At login,
     click **Advanced → Go to RPV Bill Capture (unsafe)** once. The warning only means Google hasn't reviewed the app.

### 4. On each computer
7. Delete any old `credentials\token.json`.
8. Make sure the Google account that will log in has **Editor** access to the sheet. Use **Share** in Google Sheets.
9. Run `run.bat` → **5 Test Google Sheets connection**. A browser opens: log in, allow access, and close the tab.
   The login is saved for this Windows user in `%APPDATA%\RPVBillOCR\token.json`.

If Google later shows "invalid_grant" or "token expired", delete that `token.json` and do step 9 again.

## How rows are written

For the "Bill Entry" tab:

| Column | Header | Written by this app |
|---|---|---|
| A | Bill no | the invoice number **without** the `L`, as a number (81678) |
| B | Party code | e.g. ABC |
| C | Amount | the net amount, as a number |
| D–F | RACK 1, RACK 3 | **never touched** |
| G | BILL ENTRY timestamp | the time of capture, in the same style as the existing rows |
| H–P | RACK 1/3 timestamps, Diff… | **never touched** |
| Q | (no header; you can add one) | the machine name, i.e. who entered it |

How the app picks a row and writes it:
- **Row 1 (the headers) is never written.**
- It writes into the first row from the top where A, B, C, G and Q are all empty. If someone cleared a row
  in the middle, the next bill fills that gap.
- Other people's entries (RACK names, rack timestamps, the Diff formula) are never overwritten, because only
  the five cells above are written.
- Two computers saving at the same moment: after writing, each computer reads its row back. If the other
  computer took that row, it moves its bill to the next free row, so nothing is lost or overwritten.
- If the bill number is already in column A (81678 counts as the same bill as L81678), the clerk is asked
  first. If they save it anyway, both rows are highlighted red.

Each computer's name comes from `"machine_name"` in that computer's `settings.json`, e.g. `"Counter 1"`.
If it is blank, the Windows computer name is used.

## Calibration

Open a bill in RPV Viewer, run Calibrate, and pick what your screen shows:
- **`Code: ABC / Name: … / Net : … / InvNo : …` lines.** Draw one box around all four lines, labels included.
- **A printed bill with `PARTY NAME(AP37)`.** Draw three boxes:
  - the party line, wide enough for long names
  - the Bill Amount number
  - the invoice number after `InvNo :`

The app reads the screen straight away and shows what it found. Save it only if the values are right.
If the screen resolution or Windows display scaling changes, the app refuses to read and asks you to calibrate again.

## Settings (`settings.json`)

| Key | Default | Meaning |
|---|---|---|
| `spreadsheet_id` | (asked by setup) | The ID from the sheet's web address |
| `worksheet_name` | `Bill Entry` | Tab name |
| `header_rows` | `1` | Rows at the top that are never written |
| `machine_name` | computer name | What goes in the machine column for this computer, e.g. `Counter 1` |
| `timestamp_format` | `auto` | `auto` copies the existing rows; or `time` / `datetime` |
| `sheet_invoice_with_prefix` | `false` | `false` writes 81678; `true` writes L81678 |
| `columns` | A, B, C, G, Q | Sheet column for `invoice`, `code`, `net`, `name`, `date`, `timestamp`, `machine`. Use `""` to not write one. (`name` and `date` are off by default.) |
| `invoice_prefix` / `invoice_digits` | `L` / `5` | Invoice format. Change to `6` when invoices reach L100000. |
| `confidence_threshold` | `80` | OCR confidence below this goes for checking |
| `amount_confidence_threshold` | `88` | The same check, but stricter, for the amount |
| `require_decimals` | `true` | An amount read without `.00` goes for checking |
| `tesseract_path` | auto | Full path to `tesseract.exe` if it isn't found |

## For developers

```bash
python -m unittest discover -s tests -t .
```

```bash
python -m rpv_app --accuracy tests/data/header_crops
```

The accuracy check needs real crops plus a `ground_truth.csv` (`file,code,net,inv_no`). Real test data lives in
`tests/data/`: old-layout crops, a real RPV PDF with expected values, and its pages rendered at screen resolution.
It is kept out of git because it contains customer data. **Silent errors must stay at 0.**

The clerks always capture from the screen. The PDF reader (`pdf_import.py`) is only a developer tool: an RPV PDF
has the exact bill values, so it is a free source of correct answers for testing the screen OCR.
It needs `pip install pypdf`.

```bash
python -m rpv_app --pdf-check file.pdf
```

Code layout (`rpv_app/`):

| File | Job |
|---|---|
| `__main__.py` | Command line and menu options |
| `config.py` | Settings, calibration file, party codes |
| `capture.py` | Screenshot, crop, screen-size check, Windows DPI fix |
| `ocr.py` | Image clean-up (auto-scaled), Tesseract |
| `parse.py` | Turns OCR text into checked values. No screen or network, fully unit tested. |
| `bill.py` | Reads one bill from a screenshot |
| `pdf_import.py` | Developer tool: exact values from RPV PDF printouts, for test data |
| `sheet.py` | Google Sheets: free row, duplicates, write, verify, undo |
| `store.py` | Audit log and offline upload queue |
| `session.py` | The capture workflow (testable without the UI) |
| `ui.py`, `calibrate.py` | Tkinter windows (capture, check, calibration) |
