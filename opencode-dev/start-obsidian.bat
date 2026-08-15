@echo off
rem This nested copy is kept for convenience only. The real, self-healing
rem launcher lives at the repository ROOT (one level up). Forward to it so
rem both entry points behave identically.
set "ROOT_LAUNCHER=%~dp0..\start-obsidian.bat"
if exist "%ROOT_LAUNCHER%" (
  call "%ROOT_LAUNCHER%" %*
  exit /b %errorlevel%
)
rem Fallback: if the root launcher is missing, run in place from here.
echo [info] root start-obsidian.bat not found; running from this folder.
cd /d "%~dp0"
where bun >nul 2>&1
if errorlevel 1 (
  echo [ERROR] bun not found. Run install.bat at the repository root first.
  pause
  exit /b 1
)
if not exist "%~dp0node_modules\.bun" (
  echo [info] installing dependencies...
  bun install
)
bun run --cwd "%~dp0packages\opencode" --conditions=browser src\index.ts
pause
