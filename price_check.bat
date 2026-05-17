@echo off
chcp 65001 >nul
cd /d "%~dp0"
:loop
echo [%date% %time%] 开始价格检测...
python run_price_check.py
echo [%date% %time%] 检测完成，等待5分钟...
timeout /t 300 /nobreak >nul
goto loop
