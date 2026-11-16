# Installing on a Windows PC

Everything is downloaded from GitHub, so no USB stick is needed.
Do this once on each PC. It takes about 10 minutes.

## 1. Install the two programs
1. **Tesseract OCR (64-bit)**: download the latest `tesseract-ocr-w64-setup-….exe` from
   https://github.com/UB-Mannheim/tesseract/wiki, run it, and keep the default folder (`C:\Program Files\Tesseract-OCR\`).
2. **Python 3.12 (64-bit)**: download from https://www.python.org/downloads/windows/ and run it.
   On the first screen, **tick "Add python.exe to PATH"**, then click **Install Now**.

## 2. Download the app
1. Open **https://github.com/DeveloperDoodles/rpv-bill-capture**.
2. Click the green **Code** button → **Download ZIP**.
3. Right-click the ZIP → **Extract All…** → pick the Desktop. You get a folder named `rpv-bill-capture-main`.
   You can rename it, e.g. to `RPV Bill Capture`.

## 3. Add the Google login file
Create a folder named `credentials` inside the app folder and put `client_secret.json` in it.
This file is never on GitHub, so share it privately: send it to yourself, or keep it in your Google Drive.
README.md → "Google setup" explains how to create it.

## 4. Run setup
Double-click **`setup_windows.bat`**. It installs everything, then asks two questions:
- **The Google Sheet link**: open the sheet in a browser and copy the address bar.
- **A name for this computer**, e.g. `Counter 1`. It appears in column Q, so you can see who entered each bill.

## 5. First run (open a bill in RPV first)
Double-click **`run.bat`**, then:
1. **2 Calibrate**: pick what your RPV screen shows and draw the box.
2. **3 Test reading**: check that the values match the screen.
3. **5 Test Google Sheets connection**: a browser opens once for the Google login.
4. **4 Practice capture**: try a few bills; nothing is written to the sheet.
5. **1 Start capturing.**

## Getting new versions
Double-click **`update.bat`**. It downloads the latest version from GitHub and keeps this PC's own files:
settings, calibration, the Google login file and logs.

## No internet on the PC?
Steps 1–2 and `update.bat` need internet; so does the first Google login.
For a PC without internet, download the ZIP and installers on another computer and bring them over.
Also, on a computer with internet and Python 3.12, run this inside the app folder:
```
pip download -r requirements.txt -d offline_packages --platform win_amd64 --python-version 3.12 --only-binary=:all:
```
Copy the `offline_packages` folder into the app folder on the PC; `setup_windows.bat` uses it automatically.
