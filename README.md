# RPV Bill Capture

A small Windows app for bill entry. The clerk opens a bill in **RPV Viewer** and clicks **CAPTURE BILL**.
The app reads the **bill number, party code and amount** from the screen and writes them into the
"Bill Entry" Google Sheet, together with the time and the name of the computer that entered it.

Every value is checked before it is written, so a misread number is never saved silently. When the app is
unsure, it shows the bill to the clerk and asks.

---

## Contents

1. [What you need](#1-what-you-need)
2. [One-time Google setup (`client_secret.json`)](#2-one-time-google-setup-client_secretjson)
3. [Install on each Windows PC](#3-install-on-each-windows-pc)
4. [First run on each PC](#4-first-run-on-each-pc)
5. [Daily use](#5-daily-use)
6. [Updating to a new version](#6-updating-to-a-new-version)
7. [Which files are where (and which are private)](#7-which-files-are-where-and-which-are-private)
8. [How rows are written to the sheet](#8-how-rows-are-written-to-the-sheet)
9. [Settings reference (`settings.json`)](#9-settings-reference-settingsjson)
10. [Troubleshooting](#10-troubleshooting)
11. [For developers](#11-for-developers)

---

## 1. What you need

| What | Notes |
|---|---|
| A Windows 10 or 11 PC with RPV Viewer | One per clerk. Each PC gets its own install. |
| Internet on that PC | For installing, the Google login and writing to the sheet. Bills are kept locally while offline. |
| The Google Sheet | With a tab named **Bill Entry**. Headers are in row 1. |
| A Google account per clerk (or one shared) | It must have **Editor** access to the sheet. |
| `client_secret.json` | The app's Google login file. You make it **once** in step 2 and copy it to every PC. |

---

## 2. One-time Google setup (`client_secret.json`)

The app logs in to Google Sheets with an **OAuth client**: a small file named `client_secret.json`.
You make it once, from the Google account that manages the sheet, and every PC uses the same file.

> **Keep `client_secret.json` private.** Never upload it to GitHub, post it in a group chat, or email it outside
> your team. This repository is public, and `.gitignore` keeps the file out of it.
> A safe way to move it to the PCs is a private folder in your own Google Drive.

### 2.1 Open (or create) a Google Cloud project
1. Go to **https://console.cloud.google.com** and sign in with the Google account that owns the sheet.
2. Use the project picker at the top of the page:
   - If you set this tool up before, pick that project. Its ID is the `project_id` inside the old `client_secret.json`.
   - Otherwise, click **New project**, name it `RPV Bill Capture`, and click **Create**. Then select it.

### 2.2 Turn on the Google Sheets API
1. Menu ☰ → **APIs & Services → Library**.
2. Search for **Google Sheets API**, open it, and click **Enable**. If it shows "Manage", it is already on.
   (The Google Drive API is **not** needed.)

### 2.3 Set up the consent screen (Google Auth Platform)
1. Menu ☰ → **Google Auth Platform** (older consoles: **APIs & Services → OAuth consent screen**).
2. If it shows **Get started**, fill in:
   - **App name:** `RPV Bill Capture`
   - **User support email:** your email
   - **Audience:**
     - **Internal** if your Google account is a company Google Workspace account. This is the simplest choice: no warnings and no expiry.
     - **External** for a normal @gmail.com account.
   - **Contact information:** your email
   - Agree to the policy, then click **Create**.
3. **If you chose External**, open **Audience**:
   - The **Publishing status** probably says **Testing**. In Testing mode Google **logs everyone out every 7 days**.
     Click **Publish app → Confirm** so logins last.
   - You do **not** need Google's verification. At the first login on each PC, Google shows
     *"Google hasn't verified this app"*. Click **Advanced → Go to RPV Bill Capture (unsafe)**. The warning only
     means Google hasn't reviewed your private app.
   - If you prefer to stay in Testing, add every clerk's Google account under **Test users**, and expect a re-login every week.

### 2.4 Create the OAuth client and download `client_secret.json`
1. Go to **Google Auth Platform → Clients** (older consoles: **APIs & Services → Credentials**).
2. Click **Create client** (or **Create credentials → OAuth client ID**).
3. **Application type:** **Desktop app**. **Name:** `RPV Bill Capture`. Click **Create**.
4. In the window that appears, click **Download JSON**. If you closed it, click the client's name → **Download JSON**.
5. The downloaded file has a long name such as `client_secret_1234…apps.googleusercontent.com.json`.
   **Rename it to exactly `client_secret.json`.**
   - Windows hides file extensions by default. In File Explorer, turn on **View → Show → File name extensions**
     first, otherwise you may end up with `client_secret.json.json`, which won't work.

### 2.5 Share the sheet
In Google Sheets, click **Share** and give every Google account that will log in on a PC **Editor** access.

### 2.6 If you are replacing an old setup
Earlier versions copied the Google login around, so remove that old access:
1. Go to **https://myaccount.google.com/permissions**, find the old app, and click **Remove access**.
   Do this for each Google account that used it.
2. Go to **Google Auth Platform → Clients**, and delete the old client after the new one is in place.
3. Delete any old `credentials\token.json` from the PCs and from any USB stick.
   The new version stores the login somewhere else (see section 7).

---

## 3. Install on each Windows PC

This takes about 10 minutes per PC.

### 3.1 Install Tesseract OCR (the text reader)
1. Go to **https://github.com/UB-Mannheim/tesseract/wiki**.
2. Download the latest **64-bit** installer (`tesseract-ocr-w64-setup-….exe`) and run it.
3. Keep the default install folder: `C:\Program Files\Tesseract-OCR\`.

### 3.2 Install Python 3.12
1. Go to **https://www.python.org/downloads/windows/** and download **Python 3.12.x, Windows installer (64-bit)**.
2. Run it. **On the first screen, tick "Add python.exe to PATH"** at the bottom, then click **Install Now**.
   (If you miss the tick box, run the installer again → **Modify**, or uninstall and reinstall.)

### 3.3 Download this app
1. Open **https://github.com/DeveloperDoodles/rpv-bill-capture**.
2. Click the green **Code** button → **Download ZIP**.
3. Right-click the ZIP → **Extract All…** → choose the Desktop → **Extract**.
4. You get a folder named `rpv-bill-capture-main`. You can rename it, e.g. to `RPV Bill Capture`.
   Don't run anything from inside the ZIP. Always use the extracted folder.

### 3.4 Put `client_secret.json` in a `credentials` folder
Inside the app folder, create a new folder named **`credentials`** and put `client_secret.json` (from step 2.4) in it:

```
RPV Bill Capture\
├── credentials\
│   └── client_secret.json      ← you add this
├── rpv_app\
├── run.bat
├── setup_windows.bat
├── update.bat
└── README.md …
```

### 3.5 Run setup
Double-click **`setup_windows.bat`**. It will:
1. Check Python.
2. Create a private Python environment in a `venv` folder. Only the first time takes a minute or two.
3. Install the packages the app needs.
4. Check that Tesseract and `credentials\client_secret.json` are present, with a warning if not.
5. **Ask two questions** and save the answers in `settings.json`:
   - **Google Sheet link:** open the sheet in a browser, click the address bar, copy everything
     (`https://docs.google.com/spreadsheets/d/…/edit…`), and paste it.
   - **Name for this computer:** e.g. `Counter 1`. This name is written in column **Q** for every bill
     entered on this PC, so you can see who entered what.

Read the messages at the end. `[OK]` is good. `[WARNING]` lines tell you what is still missing.

To change the answers later, run this inside the app folder (or edit `settings.json` in Notepad):
```
venv\Scripts\python.exe -m rpv_app --setup
```

---

## 4. First run on each PC

Open **RPV Viewer** on a bill, then double-click **`run.bat`**. You get this menu:

```
1. Start capturing bills
2. Calibrate screen
3. Test reading the current RPV bill
4. Practice capture (nothing is written to the sheet)
5. Test Google Sheets connection
6. Upload bills that are waiting (saved while offline)
7. Exit
```

Do these in order the first time:

### 4.1 Option 2: Calibrate
This tells the app where the bill details are on this screen.
1. A window asks what the RPV screen shows:
   - **Lines like `Code: ABC / Name: … / Net : … / InvNo : L81678`**: you will draw **one box** around those four lines, labels included.
   - **A printed bill with `PARTY NAME(AP37)` … `InvNo` … `Bill Amount`**: you will draw **three boxes**:
     around the party line (wide enough for long names), the Bill Amount number, and the invoice number.
2. After you choose, you have **3 seconds** to bring RPV to the front. The app takes a screenshot.
3. Drag a box with the mouse, then press **Enter** (or click **OK, next**). Press **Esc** to cancel.
4. The app reads the screen at once and shows what it found. If the values are right, click **Yes** to save.
   If not, click **No** and calibrate again with a slightly bigger or tighter box.

Calibrate again whenever the screen resolution or Windows display scaling changes, or the RPV window moves.
The app notices a resolution change and asks you to recalibrate.

### 4.2 Option 3: Test reading
Shows what the app reads from the current RPV bill and whether it would ask the clerk to check it.
The values should match the screen.

### 4.3 Option 5: Test Google Sheets connection
1. The first time, a **browser opens**. Log in with the Google account that has Editor access to the sheet.
2. If you see *"Google hasn't verified this app"*, click **Advanced → Go to RPV Bill Capture (unsafe)** (see 2.3).
3. Click **Continue/Allow**, then close the browser tab.
4. Back in the black window you should see the sheet name, the next free row, and this computer's name.

The login is remembered for this Windows user, so the browser won't open again.

### 4.4 Option 4: Practice capture
Same as the real thing, but **nothing is written** to the sheet. Try a few bills.

### 4.5 Option 1: Start capturing
You're live.

---

## 5. Daily use

1. Double-click `run.bat` → **1**. A small window stays on top of RPV.
2. In RPV, open a bill (use **Next** for the next one).
3. Click **CAPTURE BILL**.
   - **Green message:** saved, with the sheet row number.
   - **Check window:** the app wasn't sure. It shows the screen crop next to the values. Fix anything wrong,
     then press **Enter** to save or **Esc** to skip.
   - **"Duplicate invoice":** this bill is already in the sheet. This usually means **Next** wasn't clicked.
     Choose **No** to skip it.
   - **For a two-page bill:** go to its **last page** (where the Bill Amount is) before capturing.
4. Other buttons:
   - **Undo last:** removes the last bill this PC wrote, but only if that row still holds that bill.
   - **Upload waiting:** sends bills that were saved while the internet or Google was down.
5. When you close the window, it warns you if any bills are still waiting to upload. They are kept safely
   on the PC and offered again next time.

---

## 6. Updating to a new version

Double-click **`update.bat`**. It downloads the latest version from GitHub and installs it over the app folder.

It **keeps** everything that belongs to this PC: `settings.json`, the calibration (`rpv_regions.json`),
`credentials\`, `logs\`, `venv\` and `party_codes.csv`. It needs internet.

---

## 7. Which files are where (and which are private)

| File / folder | What it is | Private? | On GitHub? |
|---|---|---|---|
| `credentials\client_secret.json` | The app's Google login file (step 2) | **Yes** | **Never** |
| `%APPDATA%\RPVBillOCR\token.json` | This Windows user's Google login, created at the first login. Outside the app folder, so copying the folder never copies the login. | **Yes** | Never |
| `settings.json` | The Sheet ID and this PC's name (step 3.5) | Yes | Never |
| `rpv_regions.json` | This PC's calibration (step 4.1) | No | Never |
| `logs\` | Every capture: values, OCR text, crop images; plus the offline upload queue | **Yes** (bill data) | Never |
| `venv\` | Python packages for this PC, created by setup | No | Never |
| `party_codes.csv` | Optional list of valid party codes (`code,name`) | Yes | Never |
| Everything else | The program | No | Yes |

`%APPDATA%` is usually `C:\Users\<you>\AppData\Roaming`. Paste `%APPDATA%\RPVBillOCR` into the File Explorer
address bar to open it.

---

## 8. How rows are written to the sheet

| Column | Header | Written by this app |
|---|---|---|
| A | Bill no | the invoice number **without** the `L`, as a number (`L81678` → `81678`) |
| B | Party code | e.g. `ABC` |
| C | Amount | the net amount, as a number |
| D–F | RACK 1, RACK 3 | **never touched** |
| G | BILL ENTRY timestamp | the time of capture, in the same style as the existing rows |
| H–P | RACK timestamps, Diff… | **never touched** |
| Q | (no header; add one yourself if you like) | this PC's name from `settings.json` |

- **Row 1 (the headers) is never written.**
- The bill goes into the **first row from the top** where A, B, C, G and Q are all empty. If a row in the
  middle was cleared, the next bill fills that gap.
- Only those five cells are written. Rack names, rack timestamps and the Diff formula are never overwritten.
- **Two PCs saving at the same moment:** after writing, each PC reads its row back. If the other PC took that
  row, it moves its bill to the next free row, so nothing is lost.
- **Duplicates:** if the bill number is already in column A, the clerk is asked first. `81678` counts as the
  same bill as `L81678`. If they save it anyway, both rows are highlighted red.

---

## 9. Settings reference (`settings.json`)

Setup creates `settings.json` with the two values it asked for. Add any other key below **only if you need to
change it**. Anything left out uses the default. Example:

```json
{
  "spreadsheet_id": "1AbCdEf…the long ID from the sheet link…",
  "machine_name": "Counter 1"
}
```

| Key | Default | Meaning |
|---|---|---|
| `spreadsheet_id` | (asked by setup) | The long ID in the sheet link: `docs.google.com/spreadsheets/d/`**`THIS-PART`**`/edit` |
| `machine_name` | Windows computer name | Written in column Q, e.g. `Counter 1` |
| `worksheet_name` | `Bill Entry` | Tab name in the sheet |
| `header_rows` | `1` | Rows at the top that are never written |
| `columns` | invoice A, code B, net C, timestamp G, machine Q | Sheet column for `invoice`, `code`, `net`, `name`, `date`, `timestamp`, `machine`. Use `""` to not write one (`name` and `date` are off by default). Only the keys you list change. |
| `timestamp_format` | `auto` | `auto` copies the style of the existing rows; or `time` / `datetime` |
| `sheet_invoice_with_prefix` | `false` | `false` writes `81678`; `true` writes `L81678` |
| `invoice_prefix` / `invoice_digits` | `L` / `5` | Invoice format. Change to `6` when invoices reach L100000. |
| `confidence_threshold` | `80` | OCR confidence below this means the clerk checks the bill |
| `amount_confidence_threshold` | `88` | The same check, but stricter, for the amount |
| `require_decimals` | `true` | An amount read without `.00` goes to the clerk |
| `tesseract_path` | auto | Full path to `tesseract.exe` if it isn't found automatically |
| `oauth_client_file` | `credentials\client_secret.json` | Where the Google login file is |

A full example with comments is in [`settings.example.json`](settings.example.json).
If `settings.json` has a typo in a key name, the app stops and names the key.

---

## 10. Troubleshooting

| Message / problem | Fix |
|---|---|
| `Python 3.9 or newer was not found` (setup) | Install Python (3.2) with **"Add python.exe to PATH"** ticked, then run setup again. |
| `Not set up yet. Run setup_windows.bat first.` | Run `setup_windows.bat`. |
| `Tesseract OCR is not installed or could not be found` | Install Tesseract (3.1) in the default folder, or set `tesseract_path` in `settings.json`. |
| `Google login file not found` | `credentials\client_secret.json` is missing or misnamed. Check for `client_secret.json.json` (see 2.4). |
| `No spreadsheet_id set in settings.json` | Run `venv\Scripts\python.exe -m rpv_app --setup` and paste the sheet link. |
| `Spreadsheet not found, or this Google account has no access to it` | Wrong link in `settings.json`, or the logged-in account isn't an **Editor** (2.5). |
| `The sheet has no tab named 'Bill Entry'` | Rename the tab, or set `worksheet_name`. |
| Browser shows **"Access blocked"** or **"has not completed the Google verification process"** | The app is in **Testing** and this account isn't a test user. Publish the app or add the account (2.3). |
| Google login needed again every week | The app is still in **Testing**. Publish it (2.3). |
| `invalid_grant` / `Token has been expired or revoked` | Delete `%APPDATA%\RPVBillOCR\token.json`, then run option 5 and log in again. |
| `Screen size is … but calibration was done at …` | Resolution or display scaling changed. Run option 2 again. |
| `The screen has not been calibrated yet` | Run option 2. |
| Almost every bill opens the check window | The box is probably too tight or in the wrong place. Recalibrate, then check with option 3. |
| `No amount found — … go to its LAST page` | It's a multi-page bill. Capture its last page. |
| Status says **OFFLINE** or "Waiting to upload" | No internet or Google problem. Bills are kept; click **Upload waiting** or run option 6 later. |
| `settings.json has a problem: Unknown setting(s)` | A key in `settings.json` is misspelled. Compare with section 9. |

Every capture is logged in `logs\audit-<date>.jsonl`, with the screen crops in `logs\crops\`. Send these
when reporting a misread bill.

---

## 11. For developers

Run the tests (Python 3.9+, plus Tesseract for the OCR tests):
```bash
python -m unittest discover -s tests -t .
```

Measure OCR accuracy on saved crops. The folder needs `ground_truth.csv` with columns `file,code,net,inv_no`:
```bash
python -m rpv_app --accuracy tests/data/header_crops
```

Real test data (bill crops, an RPV PDF, rendered pages) lives in `tests/data/`. It is kept out of git because
it contains customer data, so tests that need it skip themselves when it's missing. **Silent errors**
(wrong and not flagged) **must stay at 0.**

The clerks always capture from the screen. `pdf_import.py` is only a developer tool: an RPV PDF holds the exact
bill values, which gives correct answers for testing the screen OCR. It needs `pip install pypdf`:
```bash
python -m rpv_app --pdf-check file.pdf
```

| File (`rpv_app/`) | Job |
|---|---|
| `__main__.py` | Command line, menu options, first-run `--setup` |
| `config.py` | Settings, calibration file, party codes |
| `capture.py` | Screenshot, crop, screen-size check, Windows DPI fix |
| `ocr.py` | Image clean-up (auto-scaled), Tesseract |
| `parse.py` | Turns OCR text into checked values. No screen or network, fully unit tested. |
| `bill.py` | Reads one bill from a screenshot (with a second reading for doubtful values) |
| `sheet.py` | Google Sheets: free row, duplicates, write, verify, undo |
| `store.py` | Audit log and offline upload queue |
| `session.py` | The capture workflow (testable without the UI) |
| `ui.py`, `calibrate.py` | Tkinter windows (capture, check, calibration) |
| `pdf_import.py`, `accuracy.py` | Developer tools for test data and accuracy |
