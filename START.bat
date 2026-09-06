@echo off
setlocal
cd /d "%~dp0MoneyPrinterTurbo"
powershell -NoProfile -Command "try{Invoke-RestMethod http://127.0.0.1:11434/api/tags -TimeoutSec 2|Out-Null;exit 0}catch{exit 1}"
if errorlevel 1 start "Ollama" /min cmd /c "ollama serve"
docker info >nul 2>&1
if errorlevel 1 if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
timeout /t 3 /nobreak >nul
docker compose up -d chatterbox webui
start "" http://127.0.0.1:8501
