@echo off
REM 工作排程器呼叫此檔。設定為每天 08:00 執行。
REM 工作目錄須為 D:\Goodprice

cd /d D:\Goodprice
call .venv\Scripts\activate.bat
python -m src.main >> logs\stdout.log 2>> logs\stderr.log
deactivate
