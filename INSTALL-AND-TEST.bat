@echo off
setlocal EnableExtensions EnableDelayedExpansion
title MoneyPrinterTurbo Ollama Director V8 - Expressive + Playwright
cd /d "%~dp0"
set "MPT=%~dp0MoneyPrinterTurbo"
set "MODEL=qwen3:8b"
set "PINNED=490e39fcf6911f4679c9b569718872c790ef0ab6"

echo ============================================================
echo  MoneyPrinterTurbo Ollama Director V8 EXPRESSIVE
echo  CLEAN INSTALL + AUTOMATED TEST GATE
echo ============================================================
echo.

for %%T in (git python docker ollama powershell) do (
  where %%T >nul 2>&1 || (
    echo [ERROR] %%T is missing or not in PATH.
    pause
    exit /b 1
  )
)

echo [1/10] Ollama...
powershell -NoProfile -Command "try{Invoke-RestMethod http://127.0.0.1:11434/api/tags -TimeoutSec 3|Out-Null;exit 0}catch{exit 1}"
if errorlevel 1 (
  start "Ollama" /min cmd /c "ollama serve"
  timeout /t 5 /nobreak >nul
)
ollama list | findstr /i /c:"%MODEL%" >nul
if errorlevel 1 ollama pull %MODEL%
if errorlevel 1 goto FAIL

echo [2/10] Docker Desktop...
docker info >nul 2>&1
if errorlevel 1 (
  if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
)
for /l %%I in (1,1,90) do (
  docker info >nul 2>&1 && goto DOCKER_READY
  timeout /t 2 /nobreak >nul
)
echo [ERROR] Docker Desktop did not become ready.
goto FAIL
:DOCKER_READY

echo [3/10] Fresh pinned MoneyPrinterTurbo source...
if exist "%MPT%" rmdir /s /q "%MPT%"
git clone https://github.com/harry0703/MoneyPrinterTurbo.git "%MPT%"
if errorlevel 1 goto FAIL
cd /d "%MPT%"
git checkout --detach %PINNED%
if errorlevel 1 goto FAIL
cd /d "%~dp0"

echo [4/10] Applying Ollama Studio base...
python "%~dp0PATCH-OLLAMA-STUDIO.py" "%MPT%"
if errorlevel 1 goto FAIL

echo [5/10] Applying Director V2...
python "%~dp0PATCH-DIRECTOR-V2.py" "%MPT%"
if errorlevel 1 goto FAIL

echo [6/10] Applying deterministic V7 fixes...
python "%~dp0FIX-MAIN-V7.py" "%MPT%"
if errorlevel 1 goto FAIL
python "%~dp0INSTALL-MEDIA-V7.py" "%MPT%" "%~dp0auto_media_v7.py"
if errorlevel 1 goto FAIL
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0CONFIGURE-V7.ps1" -RepoPath "%MPT%" -Model "%MODEL%"
if errorlevel 1 goto FAIL

echo [6b/10] Adding Chatterbox expressive narration...
python "%~dp0PATCH-CHATTERBOX-V8.py" "%MPT%"
if errorlevel 1 goto FAIL

echo [7/10] Piper model...
set "MODEL_DIR=%MPT%\models\piper"
if not exist "%MODEL_DIR%" mkdir "%MODEL_DIR%"
set "PIPER_MODEL_FILE=%MODEL_DIR%\en_US-lessac-medium.onnx"
set "PIPER_MODEL_JSON=%PIPER_MODEL_FILE%.json"
if not exist "%PIPER_MODEL_FILE%" powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri 'https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx?download=true' -OutFile '%PIPER_MODEL_FILE%'"
if not exist "%PIPER_MODEL_JSON%" powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri 'https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json?download=true' -OutFile '%PIPER_MODEL_JSON%'"
if not exist "%PIPER_MODEL_FILE%" goto FAIL
if not exist "%PIPER_MODEL_JSON%" goto FAIL

echo [8/10] Static validation...
python -m py_compile "%MPT%\webui\Main.py" || goto FAIL
python -m py_compile "%MPT%\app\services\auto_media.py" || goto FAIL
python -m py_compile "%MPT%\app\services\task.py" || goto FAIL
python -m py_compile "%MPT%\app\services\local_tts.py" || goto FAIL

echo [9/10] Docker build + start...
cd /d "%MPT%"
docker compose down >nul 2>&1
docker compose build --no-cache --pull chatterbox webui
if errorlevel 1 goto FAIL_FROM_MPT
docker compose up -d chatterbox webui
if errorlevel 1 goto FAIL_FROM_MPT
cd /d "%~dp0"
timeout /t 8 /nobreak >nul

echo [10/10] AUTOMATED TEST GATE...
call "%~dp0TEST-V8.bat"
if errorlevel 1 (
  echo.
  echo ============================================================
  echo [TEST FAILED] Installed, but NOT approved.
  echo Send me this window. Do not use the project yet.
  echo ============================================================
  pause
  exit /b 2
)

echo.
echo ============================================================
echo [APPROVED] INSTALL + TESTS PASSED
echo ============================================================
echo Ollama qwen3:8b: PASS
echo Pexels API: PASS
echo Chatterbox expressive TTS: PASS
echo Piper fallback: PASS
echo Microsoft Playwright UI: PASS
echo URL: http://127.0.0.1:8501
echo ============================================================
start "" "http://127.0.0.1:8501"
pause
exit /b 0

:FAIL_FROM_MPT
cd /d "%~dp0"
:FAIL
echo.
echo ============================================================
echo [FAILED] V8 stopped before approval.
echo It will never print APPROVED unless every test passes.
echo ============================================================
pause
exit /b 1
