@echo off
chcp 65001 >nul
title Super Workbench v4.0 (http://127.0.0.1:8765)
echo ============================================================
echo   Super Workbench v4.0 - Local Multi-Agent Studio
echo   Root: %~dp0
echo ============================================================
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8765" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul
python "%~dp0start.py"
pause
