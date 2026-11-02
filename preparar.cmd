@echo off
setlocal
cd /d "%~dp0"
set "NEXOPASS_PYTHON=%USERPROFILE%\NexoPassTools\venv\Scripts\python.exe"
if not exist "%NEXOPASS_PYTHON%" (
  if not exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
    echo Instala Python 3.13 o superior y crea el entorno NexoPassTools\venv.
    pause
    exit /b 1
  )
  "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" -m venv "%USERPROFILE%\NexoPassTools\venv"
  if errorlevel 1 exit /b 1
)
"%NEXOPASS_PYTHON%" -m pip install -r "%~dp0backend\requirements.lock"
if errorlevel 1 exit /b 1
"%NEXOPASS_PYTHON%" -B "%~dp0scripts\local.py" setup %*
if errorlevel 1 pause
