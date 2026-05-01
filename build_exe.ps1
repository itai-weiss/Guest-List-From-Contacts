$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$BuildDir = Join-Path $Root "build"
$DistDir = Join-Path $Root "dist"

if (-not (Test-Path $Python)) {
    throw "Missing virtual environment at .venv. Create it first, then install the project dependencies."
}

Push-Location $Root
try {
    foreach ($Path in @($BuildDir, $DistDir)) {
        if (Test-Path $Path) {
            Remove-Item $Path -Recurse -Force
        }
    }

    & $Python -m pip install pyinstaller
    & $Python -m PyInstaller --noconfirm --clean GuestListFromContacts.spec
}
finally {
    Pop-Location
}
