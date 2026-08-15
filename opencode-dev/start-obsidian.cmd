@echo off
title Obsidian Plan
cd /d "C:\Users\одаьтф\Desktop\ObsidianPlan\opencode-dev\"
"C:\Users\одаьтф\AppData\Roaming\npm\bun.cmd" run --cwd "C:\Users\одаьтф\Desktop\ObsidianPlan\opencode-dev\packages\opencode" --conditions=browser src\index.ts
pause
