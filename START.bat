@echo off
setlocal EnableExtensions EnableDelayedExpansion
title MoneyPrinterTurbo Ollama Director - START

set "ROOT=C:\Users\nobody\Downloads\Video-Projetos\MoneyPrinterTurbo"
set "OLLAMA_MODEL=qwen3:8b"
set "WEBUI=http://127.0.0.1:8501"
set "API=http://127.0.0.1:8080"
set "CHATTERBOX=http://127.0.0.1:4123/health"
set "SCENEPLANNER=http://127.0.0.1:4130/health"

echo ============================================================
echo MoneyPrinterTurbo - Ollama Director
echo qwen3:8b + PydanticAI + Chatterbox + Pexels
echo ============================================================
echo.

if not exist "%ROOT%\docker-compose.yml" (
    echo [FAIL] Project not found:
    echo %ROOT%
    pause
    exit /b 1
)

where docker >nul 2>nul
if errorlevel 1 (
    echo [FAIL] Docker command was not found.
    echo Start or install Docker Desktop, then run this file again.
    pause
    exit /b 1
)

where ollama >nul 2>nul
if errorlevel 1 (
    echo [FAIL] Ollama command was not found.
    pause
    exit /b 1
)

echo [1/7] Checking Ollama...
curl -s --max-time 3 http://127.0.0.1:11434/api/tags >nul 2>nul
if errorlevel 1 (
    echo Ollama is not responding. Starting Ollama...
    start "" /min ollama serve
    call :WAIT_URL "http://127.0.0.1:11434/api/tags" 45
    if errorlevel 1 (
        echo [FAIL] Ollama did not start.
        pause
        exit /b 1
    )
)
echo [PASS] Ollama is running.

echo [2/7] Checking model %OLLAMA_MODEL%...
ollama list | findstr /I /C:"%OLLAMA_MODEL%" >nul
if errorlevel 1 (
    echo Model not found. Pulling %OLLAMA_MODEL%...
    ollama pull %OLLAMA_MODEL%
    if errorlevel 1 (
        echo [FAIL] Could not pull %OLLAMA_MODEL%.
        pause
        exit /b 1
    )
)
echo [PASS] %OLLAMA_MODEL% is available.

echo [3/7] Checking Docker Desktop...
docker info >nul 2>nul
if errorlevel 1 (
    if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" (
        echo Starting Docker Desktop...
        start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
    ) else (
        echo [FAIL] Docker Desktop is not running.
        pause
        exit /b 1
    )

    set /a tries=0
    :WAIT_DOCKER
    timeout /t 3 /nobreak >nul
    docker info >nul 2>nul
    if not errorlevel 1 goto DOCKER_READY
    set /a tries+=1
    if !tries! GEQ 60 (
        echo [FAIL] Docker Desktop did not become ready.
        pause
        exit /b 1
    )
    goto WAIT_DOCKER
)

:DOCKER_READY
echo [PASS] Docker Desktop is ready.

echo [4/7] Validating Docker Compose...
cd /d "%ROOT%"
docker compose config >nul
if errorlevel 1 (
    echo [FAIL] docker-compose.yml is invalid.
    echo.
    docker compose config
    pause
    exit /b 1
)
echo [PASS] Docker Compose is valid.

echo [5/7] Starting MoneyPrinterTurbo services...
docker compose up -d scene-planner chatterbox webui api
if errorlevel 1 (
    echo.
    echo [FAIL] Docker could not start the services.
    echo.
    docker compose ps
    echo.
    echo Last logs:
    docker compose logs --tail 120
    pause
    exit /b 1
)

echo [6/7] Waiting for local AI services...

call :WAIT_URL "%SCENEPLANNER%" 120
if errorlevel 1 (
    echo [FAIL] PydanticAI Scene Planner did not become ready.
    docker logs moneyprinterturbo-scene-planner --tail 120
    pause
    exit /b 1
)
echo [PASS] PydanticAI Scene Planner

call :WAIT_URL "%CHATTERBOX%" 180
if errorlevel 1 (
    echo [WARN] Chatterbox is not healthy yet.
    echo The first model load can take longer.
    echo The normal pipeline can still fall back to Piper / Edge TTS.
) else (
    echo [PASS] Chatterbox expressive narration
)

call :WAIT_URL "%WEBUI%" 120
if errorlevel 1 (
    echo [FAIL] MoneyPrinterTurbo WebUI did not become ready.
    docker logs moneyprinterturbo-webui --tail 150
    pause
    exit /b 1
)
echo [PASS] MoneyPrinterTurbo WebUI

echo [7/7] Ready.
echo.
echo ============================================================
echo MoneyPrinterTurbo is running
echo WebUI:         %WEBUI%
echo API:           %API%
echo Scene Planner: http://127.0.0.1:4130
echo Chatterbox:    http://127.0.0.1:4123
echo Ollama Model:  %OLLAMA_MODEL%
echo ============================================================
echo.

start "" "%WEBUI%"
exit /b 0


:WAIT_URL
set "CHECK_URL=%~1"
set /a "MAX_SECONDS=%~2"
set /a "ELAPSED=0"

:WAIT_URL_LOOP
curl -s -f --max-time 4 "%CHECK_URL%" >nul 2>nul
if not errorlevel 1 exit /b 0

timeout /t 2 /nobreak >nul
set /a ELAPSED+=2
if !ELAPSED! GEQ !MAX_SECONDS! exit /b 1
goto WAIT_URL_LOOP
