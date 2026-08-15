@echo off
chcp 65001 >nul 2>&1
title Obsidian Plan
rem Paths are derived from %~dp0 so this file stays pure ASCII even when
rem the user profile contains non-ASCII characters.
set "ROOT=%~dp0"
set "ROOTF=%ROOT:\=/%"
set "LOG=%ROOT%obsidian-launch.log"
rem Truncate per run so a stale ANSI frame can never be replayed by `type`.
type nul > "%LOG%"
cd /d "%ROOT%opencode-dev"
rem stdout MUST stay on the console: it carries the TUI frame, and a
rem redirected stdout also makes stdout.columns/rows undefined, which
rem collapses the renderer to its 80x24 fallback. stderr only.
bun run --cwd "%ROOTF%opencode-dev/packages/opencode" --conditions=browser src/index.ts 2>> "%LOG%"
set "RC=%errorlevel%"
if not "%RC%"=="0" (
  echo.
  echo  ============================================
  echo   Obsidian exited with code %RC%.
  echo   Error details are in: %LOG%
  echo   ============================================
  type "%LOG%"
  echo.
)
pause
