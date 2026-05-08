@echo off
REM Launch Goodprice Streamlit UI on http://localhost:8501
REM Double-click to open. Close window or press Ctrl+C to stop.

cd /d D:\Goodprice

if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] .venv not found. Run scripts\setup.ps1 first.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

REM Open browser after 3 seconds (give server time to start)
start "" /B cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8501"

echo.
echo  ========================================
echo   Goodprice — Coupang TW Deal Tracker
echo  ========================================
echo.
echo  URL: http://localhost:8501
echo  Press Ctrl+C or close this window to stop.
echo.

streamlit run web/app.py --server.headless true --browser.gatherUsageStats false
