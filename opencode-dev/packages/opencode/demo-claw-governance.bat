@echo off
echo ========================================
echo Claw/Cloud 治理引擎运行时演示
echo ========================================
echo.
echo 这个脚本会：
echo 1. 创建一个 cloud（治理单元）
echo 2. 请求派生 agent（需要控制平面批准）
echo 3. Agent 加入 cloud
echo 4. 激活 cloud
echo 5. 打印完整的治理事件日志
echo.
echo 按任意键开始...
pause > nul

cd /d "%~dp0"
bun run test-claw-live.ts

echo.
echo ========================================
echo 演示完成！
echo ========================================
echo.
echo 你刚才看到的 5 条治理事件证明：
echo - cloud.created    :: 创建治理单元
echo - spawn.requested  :: 请求派生 agent
echo - spawn.approved   :: 控制平面批准
echo - member.joined    :: Agent 加入 cloud
echo - cloud.activated  :: 激活执行
echo.
echo 这些事件来自 ClawManager（进程内存）。
echo 在真实应用里（TUI/Server），每次 agent 派生 agent 都会产生这些记录。
echo.
pause
