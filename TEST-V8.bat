@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "MPT=%~dp0MoneyPrinterTurbo"
set "VENV=%~dp0.test-venv"
if not exist "%MPT%\webui\Main.py" (
  echo [FAIL] MoneyPrinterTurbo is not installed.
  exit /b 1
)
if not exist "%VENV%\Scripts\python.exe" (
  echo [TEST] Creating isolated Microsoft Playwright test environment...
  python -m venv "%VENV%" || exit /b 1
  "%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check --quiet requests playwright || exit /b 1
  "%VENV%\Scripts\python.exe" -m playwright install chromium || exit /b 1
)
echo [TEST] Running Ollama, Pexels, Chatterbox, Piper and Microsoft Playwright checks...
"%VENV%\Scripts\python.exe" "%~dp0VERIFY-V8.py" "%MPT%"
exit /b %ERRORLEVEL%
