@echo off
REM =============================================================
REM  Obsidian Plan — 便携版打包脚本
REM  把整个 monorepo + Bun 运行时复制到 dist-portable 目录
REM =============================================================
setlocal enabledelayedexpansion

set SRC=%~dp0
set DST=%~dp0..\..\..\dist-portable

echo.
echo ============================================
echo  Obsidian Plan 便携版打包工具
echo ============================================
echo.
echo 源目录: %SRC%
echo 目标目录: %DST%
echo.

REM 清理旧的输出
if exist "%DST%" (
    echo 🧹 清理旧的输出目录...
    rmdir /s /q "%DST%"
)
mkdir "%DST%"

REM 1. 复制 Bun 运行时
echo 📦 复制 Bun 运行时...
for /f "tokens=*" %%i in ('where bun.exe 2^>nul') do (
    set BUN_EXE=%%i
    goto :found_bun
)
:bun_npm
set BUN_EXE=%APPDATA%\npm\node_modules\bun\bin\bun.exe
if not exist "%BUN_EXE%" (
    echo ❌ 未找到 bun.exe！请确保已安装 Bun
    pause
    exit /b 1
)
:found_bun
echo    Bun 路径: %BUN_EXE%
copy "%BUN_EXE%" "%DST%\bun.exe" > nul
echo    ✅ bun.exe

REM 2. 复制 monorepo 源码（排除 .git 和已生成文件）
echo.
echo 📦 复制 monorepo 源码...

REM 复制 packages 目录（排除 node_modules 和生成物）
robocopy "%SRC%" "%DST%\packages\opencode" ^
    /E /NFL /NDL /NJH /NJS /nc /ns /np ^
    /XD node_modules dist dist-exe dist-portable .git ^
    /XF "*.output"
echo    ✅ packages/opencode/src/

REM 复制 packages/core
robocopy "%SRC%\..\core" "%DST%\packages\core" ^
    /E /NFL /NDL /NJH /NJS /nc /ns /np ^
    /XD node_modules dist .git
echo    ✅ packages/core/

REM 3. 复制根级 node_modules（真正的依赖）
echo.
echo 📦 复制根级依赖（node_modules）...
echo    这一步可能需要几分钟，请耐心等待...
robocopy "%SRC%\..\..\node_modules" "%DST%\node_modules" ^
    /E /NFL /NDL /NJH /NJS /nc /ns /np
echo    ✅ node_modules/

REM 4. 复制 packages/opencode/node_modules（包级依赖）
echo.
echo 📦 复制包级依赖...
robocopy "%SRC%\node_modules" "%DST%\packages\opencode\node_modules" ^
    /E /NFL /NDL /NJH /NJS /nc /ns /np
echo    ✅ packages/opencode/node_modules/

REM 5. 复制 workspace 相关配置文件
echo.
echo 📦 复制配置文件...
copy "%SRC%\..\..\bun.lock" "%DST%\" > nul 2>&1
copy "%SRC%\..\..\package.json" "%DST%\" > nul 2>&1
copy "%SRC%\..\..\bunfig.toml" "%DST%\" > nul 2>&1
echo    ✅ 根配置文件

REM 6. 生成启动脚本
echo.
echo 📝 生成启动脚本...

REM 启动-TUI.bat
echo @echo off > "%DST%\启动-TUI.bat"
echo set OPENCODE_CLAW_GOVERNANCE=1 >> "%DST%\启动-TUI.bat"
echo set OPENCODE_SERVER_PASSWORD=claw-demo >> "%DST%\启动-TUI.bat"
echo cd /d "%%~dp0packages\opencode" >> "%DST%\启动-TUI.bat"
echo "%%~dp0bun.exe" run --conditions=browser "./src/index.ts" tui >> "%DST%\启动-TUI.bat"
echo pause >> "%DST%\启动-TUI.bat"
echo    ✅ 启动-TUI.bat

REM 启动-Server.bat
echo @echo off > "%DST%\启动-Server.bat"
echo set OPENCODE_CLAW_GOVERNANCE=1 >> "%DST%\启动-Server.bat"
echo set OPENCODE_SERVER_PASSWORD=claw-demo >> "%DST%\启动-Server.bat"
echo cd /d "%%~dp0packages\opencode" >> "%DST%\启动-Server.bat"
echo echo 访问 http://127.0.0.1:4096 （密码: claw-demo） >> "%DST%\启动-Server.bat"
echo "%%~dp0bun.exe" run --conditions=browser "./src/index.ts" serve --port 4096 >> "%DST%\启动-Server.bat"
echo pause >> "%DST%\启动-Server.bat"
echo    ✅ 启动-Server.bat

REM 演示-Claw.bat
echo @echo off > "%DST%\演示-Claw.bat"
echo cd /d "%%~dp0packages\opencode" >> "%DST%\演示-Claw.bat"
echo echo Claw/Cloud 治理引擎演示 >> "%DST%\演示-Claw.bat"
echo pause >> "%DST%\演示-Claw.bat"
echo "%%~dp0bun.exe" run --conditions=browser "./src/index.ts" claw demo >> "%DST%\演示-Claw.bat"
echo pause >> "%DST%\演示-Claw.bat"
echo    ✅ 演示-Claw.bat

REM obsidian.bat（通用命令行入口）
echo @echo off > "%DST%\obsidian.bat"
echo cd /d "%%~dp0packages\opencode" >> "%DST%\obsidian.bat"
echo "%%~dp0bun.exe" run --conditions=browser "./src/index.ts" %%* >> "%DST%\obsidian.bat"
echo    ✅ obsidian.bat

REM 7. 统计大小
echo.
echo 📊 统计信息...
for /f %%a in ('powershell -Command "(Get-ChildItem -Path '%DST%' -Recurse -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum / 1MB"') do (
    echo    总大小: %%a MB
)

echo.
echo ============================================
echo  ✨ 打包完成！
echo ============================================
echo.
echo 便携版位置: %DST%
echo.
echo 使用方法：
echo   1. 把 dist-portable 文件夹复制到任意 Windows 机器
echo   2. 双击 启动-TUI.bat    → 全屏交互界面
echo   3. 双击 启动-Server.bat → HTTP 服务（访问 :4096）
echo   4. 双击 演示-Claw.bat   → 治理引擎演示
echo   5. obsidian.bat --help  → 命令行帮助
echo.
pause
