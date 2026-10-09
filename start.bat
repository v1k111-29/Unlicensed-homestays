@echo off
rem Verified Stays - one-click local start (Windows).
rem Uses the existing .venv (never creates another). All logic lives in scripts\dev_start.py.
rem There is no separate client: the app is server-rendered, so one Django server serves
rem both the officer/admin screens and the public tourist page.
rem
rem   start.bat             prepare everything, then start the server on http://127.0.0.1:8000
rem   start.bat --no-browser   same, without opening the browser
rem   start.bat --reset-accounts   recreate the demo accounts with new passwords
setlocal
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [start] .venv not found at %CD%\.venv
  echo [start] Create it once with Python 3.11, then run: .venv\Scripts\python.exe tasks.py setup
  pause
  exit /b 1
)
"%PY%" scripts\dev_start.py %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [start] Stopped with exit code %RC%. Read the message above.
  pause
)
exit /b %RC%
