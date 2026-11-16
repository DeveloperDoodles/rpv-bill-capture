# Downloads the latest version of RPV Bill Capture from GitHub and installs it over this folder.
# This computer's own files are never touched: settings.json, rpv_regions.json, party_codes.csv,
# credentials\, logs\ and venv\.
$ErrorActionPreference = "Stop"
$Repo = "DeveloperDoodles/rpv-bill-capture"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$keep = @("settings.json", "rpv_regions.json", "party_codes.csv", "credentials", "logs", "venv", "update.bat")

$tmp = Join-Path $env:TEMP ("rpv_update_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
    Write-Host "Downloading the latest version from github.com/$Repo ..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $zip = Join-Path $tmp "app.zip"
    Invoke-WebRequest -Uri "https://github.com/$Repo/archive/refs/heads/main.zip" -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath $tmp
    $src = Get-ChildItem -Path $tmp -Directory | Select-Object -First 1
    if (-not (Test-Path (Join-Path $src.FullName "rpv_app"))) { throw "The download does not look like RPV Bill Capture." }

    Get-ChildItem -Path $src.FullName -Force | Where-Object { $keep -notcontains $_.Name } | ForEach-Object {
        $dest = Join-Path $here $_.Name
        if (Test-Path $dest) { Remove-Item -Path $dest -Recurse -Force }
        Copy-Item -Path $_.FullName -Destination $dest -Recurse -Force
    }
}
finally {
    Remove-Item -Path $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

$py = Join-Path $here "venv\Scripts\python.exe"
if (Test-Path $py) {
    Write-Host "Updating packages ..."
    & $py -m pip install --quiet -r (Join-Path $here "requirements.txt")
    & $py -m rpv_app --version
} else {
    Write-Host "Not set up yet: run setup_windows.bat next."
}
Write-Host "Update finished."
