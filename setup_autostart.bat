@echo off
chcp 65001 >nul
echo 正在设置价格监控开机自动启动...

set TASK_NAME=京东价格监控
set BAT_PATH=%~dp0price_check.bat

schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1

schtasks /create ^
  /tn "%TASK_NAME%" ^
  /tr "\"%BAT_PATH%\"" ^
  /sc ONLOGON ^
  /rl HIGHEST ^
  /f

if %errorlevel% == 0 (
    echo.
    echo ✅ 设置成功！下次开机后价格监控将自动运行。
    echo.
    echo 现在立即启动一次测试？按任意键开始，Ctrl+C 取消
    pause >nul
    start "京东价格监控" "%BAT_PATH%"
) else (
    echo ❌ 设置失败，请右键此文件选择"以管理员身份运行"
)
pause
