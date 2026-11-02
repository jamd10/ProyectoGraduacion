@echo off
setlocal
cd /d "%~dp0"
set "NEXOPASS_PYTHON=%USERPROFILE%\NexoPassTools\venv\Scripts\python.exe"
if not exist "%NEXOPASS_PYTHON%" (
  echo Primero ejecuta preparar.cmd.
  pause
  exit /b 1
)
"%NEXOPASS_PYTHON%" -B "%~dp0scripts\local.py" run %*
if errorlevel 1 pause
