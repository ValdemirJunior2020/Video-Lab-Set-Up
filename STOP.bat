@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "MPT=%~dp0MoneyPrinterTurbo"
if not exist "%MPT%\docker-compose.yml" (
  echo [INFO] Installed project not found.
  pause
  exit /b 0
)
cd /d "%MPT%"
docker compose down
echo [SUCCESS] MoneyPrinterTurbo Ollama Studio stopped.
pause
