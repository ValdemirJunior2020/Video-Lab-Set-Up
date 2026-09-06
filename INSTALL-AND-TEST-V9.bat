@echo off
setlocal EnableExtensions
title MoneyPrinterTurbo PydanticAI Scene Planner V9

set "DEFAULT_ROOT=C:\Users\nobody\Downloads\Video-Projetos\MoneyPrinterTurbo"
set "ROOT=%~1"
if "%ROOT%"=="" set "ROOT=%DEFAULT_ROOT%"

echo ============================================================
echo MoneyPrinterTurbo - PydanticAI Scene Planner V9.1 SAFE MEDIA
echo Ollama qwen3:8b + validated structured scene output
echo Microsoft Playwright approval gate
echo ============================================================
echo.
echo Project: %ROOT%
echo.

where python >nul 2>nul || (
  echo [FAIL] Python is required.
  exit /b 1
)
where docker >nul 2>nul || (
  echo [FAIL] Docker Desktop is required.
  exit /b 1
)

echo [1/6] Applying patch with backup...
python "%~dp0APPLY-PYDANTIC-SCENE-AGENT.py" "%ROOT%"
if errorlevel 1 goto FAIL

echo [2/6] Validating Docker Compose...
pushd "%ROOT%"
docker compose config >nul
if errorlevel 1 (
  popd
  goto FAIL
)

echo [3/6] Building local PydanticAI scene-planner service...
docker compose build --pull scene-planner
if errorlevel 1 (
  popd
  goto FAIL
)

echo [4/6] Starting scene-planner + existing services...
docker compose up -d scene-planner chatterbox webui
if errorlevel 1 (
  popd
  goto FAIL
)
popd

echo [5/6] Preparing Microsoft Playwright test environment...
set "VENV=%~dp0.test-venv"
if not exist "%VENV%\Scripts\python.exe" (
  python -m venv "%VENV%"
  if errorlevel 1 goto FAIL
  "%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check --quiet requests playwright
  if errorlevel 1 goto FAIL
  "%VENV%\Scripts\python.exe" -m playwright install chromium
  if errorlevel 1 goto FAIL
)

echo [6/6] Running real Ollama structured-output + Playwright tests...
"%VENV%\Scripts\python.exe" "%~dp0VERIFY-PYDANTIC-SCENE-AGENT.py" "%ROOT%"
if errorlevel 1 goto FAIL

echo.
echo ============================================================
echo [APPROVED] PYDANTICAI SCENE PLANNER V9.1 SAFE MEDIA PASSED
echo ============================================================
echo Ollama qwen3:8b structured planning: PASS
echo Pydantic validation: PASS
echo Pexels configuration/API: PASS
echo Chatterbox service: PASS
echo Microsoft Playwright UI: PASS
echo.
echo Your existing .git and .env were not touched.
echo ============================================================
pause
exit /b 0

:FAIL
echo.
echo ============================================================
echo [NOT APPROVED] A TEST FAILED
echo Do not rely on the new planner until the error above is fixed.
echo Your original edited files are backed up under:
echo %ROOT%\.ollama-studio-backups
echo ============================================================
pause
exit /b 1
