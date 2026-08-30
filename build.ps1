# build.ps1
# Rebuilds graph_app.exe from scratch.
# Run from the project folder (same one containing graph_app.py, launcher.py,
# launcher.spec, find_metadata_deps.py) with your venv activated.
#
# Usage:  .\build.ps1

$ErrorActionPreference = "Stop"

Write-Host "== Checking required packages ==" -ForegroundColor Cyan
pip show streamlit streamlit-desktop-app pyinstaller 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing missing build/runtime dependencies..." -ForegroundColor Yellow
    pip install streamlit pandas plotly openpyxl kaleido streamlit-desktop-app pyinstaller
}

Write-Host "== Discovering packages that need --copy-metadata ==" -ForegroundColor Cyan
python find_metadata_deps.py

Write-Host "== Cleaning previous build artifacts ==" -ForegroundColor Cyan
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build, dist

Write-Host "== Running PyInstaller ==" -ForegroundColor Cyan
pyinstaller launcher.spec

if ($LASTEXITCODE -eq 0) {
    Write-Host "== Zipping dist\graph_app for distribution ==" -ForegroundColor Cyan
    $zipPath = "GraphApp.zip"
    Remove-Item -Force -ErrorAction SilentlyContinue $zipPath
    Compress-Archive -Path "dist\graph_app" -DestinationPath $zipPath

    Write-Host ""
    Write-Host "Build succeeded. Folder is at: dist\graph_app\" -ForegroundColor Green
    Write-Host "Run it with:  .\dist\graph_app\graph_app.exe" -ForegroundColor Green
    Write-Host "Share it as:  $zipPath (self-contained, no install needed —" -ForegroundColor Green
    Write-Host "              unzip on the target PC and run graph_app.exe inside)" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "Build failed. Scroll up for the PyInstaller error." -ForegroundColor Red
    Write-Host "If it's a new 'PackageNotFoundError: <pkg>', add '<pkg>' to" -ForegroundColor Red
    Write-Host "METADATA_PACKAGES in launcher.spec and re-run this script." -ForegroundColor Red
}
