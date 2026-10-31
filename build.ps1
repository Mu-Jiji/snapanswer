# 构建单文件/目录版 exe（可选）
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    py -3.12 -m venv .venv
}
& ".venv\Scripts\python.exe" -m pip install --upgrade pip
& ".venv\Scripts\python.exe" -m pip install -e ".[build]"

& ".venv\Scripts\pyinstaller.exe" `
    --noconfirm --clean --windowed `
    --name SnapAnswer `
    --icon "assets\icon.ico" `
    --add-data "assets;assets" `
    --collect-all rapidocr_onnxruntime `
    --collect-all onnxruntime `
    --hidden-import pynput.keyboard._win32 `
    launcher.py

Write-Host ""
Write-Host "构建完成：dist\SnapAnswer\SnapAnswer.exe"
