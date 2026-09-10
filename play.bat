@echo off
REM Source launcher. scripts\launch.py creates/repairs the runtime only as needed.
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "scripts\launch.py" %*
  goto finished
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3 "scripts\launch.py" %*
  goto finished
)
where python >nul 2>nul
if not errorlevel 1 (
  python "scripts\launch.py" %*
  goto finished
)
echo Install Python 3.10 or newer from https://www.python.org/downloads/ and reopen Play.
pause
exit /b 1

:finished
set "MM_LAUNCH_EXIT=%ERRORLEVEL%"
if not "%MM_LAUNCH_EXIT%"=="0" pause
exit /b %MM_LAUNCH_EXIT%
