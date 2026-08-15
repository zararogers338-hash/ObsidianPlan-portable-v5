@echo off
setlocal enabledelayedexpansion
title Obsidian Plan - Install bun

echo.
echo  ================================================
echo   Installing bun for Obsidian Plan
echo  ================================================
echo.

where bun.exe >nul 2>&1
if not errorlevel 1 (
  echo  [OK] bun already installed.
  timeout /t 2 /nobreak >nul
  exit /b 0
)
where bun >nul 2>&1
if not errorlevel 1 (
  echo  [OK] bun already installed.
  timeout /t 2 /nobreak >nul
  exit /b 0
)

echo  [Install] Downloading bun...
powershell -NoProfile -Command "Invoke-RestMethod bun.sh/install.ps1 | Invoke-Expression" 2>&1 | findstr /C:"bun was installed"

where bun >nul 2>&1
if errorlevel 1 (
  echo  [ERROR] bun install failed. Install manually: https://bun.sh
  pause
  exit /b 1
)

echo.
echo  [OK] bun installed successfully.
echo  Now double-click start-obsidian.bat to launch Obsidian.
echo.
pause
