@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title Obsidian Plan

rem Always operate from the folder this .bat lives in (repo root).
cd /d "%~dp0"

set "SRC_DIR=%~dp0opencode-dev"
set "SRC_PKG=%SRC_DIR%\packages\opencode"
rem Forward-slash variants for the command line (bun eats backslash sequences).
set "SRC_PKG_F=%SRC_PKG:\=/%"
set "LOG=%~dp0obsidian-launch.log"

rem ── Web search (Exa) ────────────────────────────────────────────────────────
rem Free tier first; optionally set EXA_API_KEY in the environment for fallback.
set OPENCODE_ENABLE_EXA=1

echo.
echo  ================================================
echo   Obsidian Plan - Panshi MICP Research System
echo  ================================================
echo.
echo   Log file: %LOG%
echo.

rem ---- Step 1/4 : source present? ----
echo  [Step 1/4] Checking source...
if not exist "%SRC_PKG%\src\index.ts" (
  echo        [ERROR] Source not found:
  echo                %SRC_PKG_F%/src/index.ts
  echo          Put this .bat in the ObsidianPlan root folder.
  goto :fail
)
echo        [OK] Source found

rem ---- Step 2/4 : bun available? ----
echo.
echo  [Step 2/4] Checking bun runtime...
where bun >nul 2>&1
if errorlevel 1 (
  if exist "%USERPROFILE%\.bun\bin\bun.exe" set "PATH=%USERPROFILE%\.bun\bin;%PATH%"
)
where bun >nul 2>&1
if errorlevel 1 (
  echo        bun not found - running installer...
  if exist "%~dp0install.bat" (
    call "%~dp0install.bat"
  ) else (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm bun.sh/install.ps1 | iex"
    if exist "%USERPROFILE%\.bun\bin\bun.exe" set "PATH=%USERPROFILE%\.bun\bin;%PATH%"
  )
)
where bun >nul 2>&1
if errorlevel 1 (
  echo        [ERROR] bun still not available. Run install.bat first.
  goto :fail
)
echo        [OK] bun ready

rem ---- Step 3/4 : dependencies installed? ----
echo.
echo  [Step 3/4] Checking dependencies...
if exist "%SRC_DIR%\node_modules\.bun" (
  echo        [OK] Dependencies present
  goto :launch
)
echo        Installing dependencies (first run downloads packages)...
pushd "%SRC_DIR%"
bun install
set "IRC=%errorlevel%"
popd
if not "%IRC%"=="0" (
  echo        [ERROR] bun install failed (exit %IRC%). Check network/npm.
  goto :fail
)
if not exist "%SRC_DIR%\node_modules\.bun" (
  echo        [ERROR] install ran but node_modules is still missing.
  goto :fail
)
echo        [OK] Dependencies installed

rem ---- Step 4/4 : launch (errors pause, never flash-close) ----
:launch
echo.
echo  [Step 4/4] Launching Obsidian Plan...
echo.

rem Build a child script with forward slashes and a trailing pause so the
rem window STAYS OPEN on any error and shows the real message.
set "LAUNCHER=%~dp0_start_obsidian.cmd"
(
  echo @echo off
  echo chcp 65001 ^>nul 2^>^&1
  echo title Obsidian Plan
  echo rem Paths are derived from %%~dp0 so this file stays pure ASCII even when
  echo rem the user profile contains non-ASCII characters.
  echo set "ROOT=%%~dp0"
  echo set "ROOTF=%%ROOT:\=/%%"
  echo set "LOG=%%ROOT%%obsidian-launch.log"
  echo rem Truncate per run so a stale ANSI frame can never be replayed by `type`.
  echo type nul ^> "%%LOG%%"
  echo cd /d "%%ROOT%%opencode-dev"
  echo rem stdout MUST stay on the console: it carries the TUI frame, and a
  echo rem redirected stdout also makes stdout.columns/rows undefined, which
  echo rem collapses the renderer to its 80x24 fallback. stderr only.
  echo bun run --cwd "%%ROOTF%%opencode-dev/packages/opencode" --conditions=browser src/index.ts 2^>^> "%%LOG%%"
  echo set "RC=%%errorlevel%%"
  echo if not "%%RC%%"=="0" ^(
  echo   echo.
  echo   echo  ============================================
  echo   echo   Obsidian exited with code %%RC%%.
  echo   echo   Error details are in: %%LOG%%
  echo   echo   ============================================
  echo   type "%%LOG%%"
  echo   echo.
  echo ^)
  echo pause
) > "%LAUNCHER%"

where wt >nul 2>&1
if not errorlevel 1 (
  start "Obsidian Plan" wt "%LAUNCHER%"
) else (
  start "Obsidian Plan" cmd /k "%LAUNCHER%"
)

echo  [OK] Launched in a new window.
echo  This window stays open - the app runs in the other one.
echo  (Close this one with any key.)
pause >nul
exit /b 0

:fail
echo.
echo  ================================================
echo   Something went wrong. Details above.
echo   This window will NOT close - read the message.
echo  ================================================
echo.
pause
exit /b 1
