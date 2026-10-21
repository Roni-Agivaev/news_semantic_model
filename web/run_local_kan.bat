@echo off
rem Daily Kan News scrape from this PC (Kan blocks Vercel's servers).
rem Run by Windows Task Scheduler; output is appended to web\run_local.log.
rem Needs web\.env with DATABASE_URL and the repo's .venv.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
echo ===== %date% %time% >> run_local.log
"%~dp0..\.venv\Scripts\python.exe" run_local.py "Kan News" >> run_local.log 2>&1
