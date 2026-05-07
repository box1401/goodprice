# 一鍵建環境。在 D:\Goodprice 下執行：
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

Write-Host "[1/5] 建立 venv (Python 3.11)..."
if (-not (Test-Path ".venv")) {
    & py -3.11 -m venv .venv
}

Write-Host "[2/5] 啟用 venv..."
& .\.venv\Scripts\Activate.ps1

Write-Host "[3/5] 升級 pip..."
& python -m pip install --upgrade pip

Write-Host "[4/5] 安裝依賴..."
& python -m pip install -r requirements.txt

Write-Host "[5/5] 安裝 Playwright Chromium..."
& python -m playwright install chromium

# 複製 config
if (-not (Test-Path "config.yaml")) {
    Copy-Item config.yaml.template config.yaml
    Write-Host ""
    Write-Host "已建立 config.yaml。編輯它填入：" -ForegroundColor Yellow
    Write-Host "  - regions[].url  (火箭跨境韓國/美國 分類網址)" -ForegroundColor Yellow
    Write-Host "  - telegram.bot_token / chat_id (測試時)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "完成。下一步：" -ForegroundColor Green
Write-Host "  1. 編輯 config.yaml 填入分類 URL"
Write-Host "  2. 跑 discover 確認 selector：python -m src.main --discover"
Write-Host "  3. 跑 dry-run 測試流程：python -m src.main --dry-run"
Write-Host "  4. 啟動介面：streamlit run web/app.py"
