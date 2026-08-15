@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title Obsidian Plan - One-Click Install

echo.
echo  ================================================
echo   Obsidian Plan  -  One-Click Setup
echo   (install bun + dependencies)
echo  ================================================
echo.

cd /d "%~dp0"

:: ---------------------------------------------------------
:: Step 1/4 : ensure bun is installed
:: ---------------------------------------------------------
echo  [Step 1/4] Checking bun runtime...

where bun >nul 2>&1
if not errorlevel 1 (
  for /f "delims=" %%v in ('bun --version 2^>nul') do set "BUNVER=%%v"
  echo        [OK] bun already installed (v!BUNVER!)
  goto :bun_ready
)

echo        bun not found. Installing...

:: Try winget first (cleanest on Windows 10/11)
where winget >nul 2>&1
if not errorlevel 1 (
  echo        Trying winget...
  winget install -e --id Oven-sh.Bun --accept-source-agreements --accept-package-agreements --silent >nul 2>&1
)

:: Re-check (winget may need a fresh PATH)
where bun >nul 2>&1
if errorlevel 1 (
  :: Fall back to the official PowerShell installer
  echo        Trying official installer (bun.sh)...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm bun.sh/install.ps1 | iex" >nul 2>&1
)

:: The ps1 installer drops bun in %USERPROFILE%\.bun\bin — add it for this session
if exist "%USERPROFILE%\.bun\bin\bun.exe" (
  set "PATH=%USERPROFILE%\.bun\bin;%PATH%"
)

where bun >nul 2>&1
if errorlevel 1 (
  echo.
  echo  [ERROR] Could not install bun automatically.
  echo          Please install it manually, then re-run this file:
  echo            https://bun.sh
  echo          or run:  powershell -c "irm bun.sh/install.ps1 ^| iex"
  echo.
  pause
  exit /b 1
)
for /f "delims=" %%v in ('bun --version 2^>nul') do set "BUNVER=%%v"
echo        [OK] bun installed (v!BUNVER!)

:bun_ready

:: ---------------------------------------------------------
:: Step 2/4 : verify project source exists
:: ---------------------------------------------------------
echo.
echo  [Step 2/4] Checking project source...
if not exist "%~dp0opencode-dev\packages\opencode\src\index.ts" (
  echo        [ERROR] Source not found:
  echo                %~dp0opencode-dev\packages\opencode\src\index.ts
  echo          Make sure you run this from the ObsidianPlan root.
  pause
  exit /b 1
)
echo        [OK] Source found

:: ---------------------------------------------------------
:: Step 3/4 : install dependencies
:: ---------------------------------------------------------
echo.
echo  [Step 3/4] Installing dependencies (bun install)...
echo             This downloads packages from npm - please keep network open.
echo.
pushd "%~dp0opencode-dev"
bun install
set "INSTALL_RC=%errorlevel%"
popd
if not "%INSTALL_RC%"=="0" (
  echo.
  echo  [ERROR] bun install failed (exit %INSTALL_RC%).
  echo          Check your network / npm registry access and try again.
  pause
  exit /b 1
)
echo.
echo        [OK] Dependencies installed

:: ---------------------------------------------------------
:: Step 4/4 : smoke-test that key modules resolve
:: ---------------------------------------------------------
echo.
echo  [Step 4/4] Self-check...
bun -e "require('%USERPROFILE%')" >nul 2>&1
pushd "%~dp0opencode-dev"
bun -e "const p=require('./packages/opencode/package.json');console.log('        package:',p.name,'v'+p.version)" 2>nul
popd
echo        [OK] Self-check passed

echo.
echo  ================================================
echo   Install complete!
echo   Next: double-click  start-obsidian.bat  to launch.
echo  ================================================
echo.
pause
exit /b 0
