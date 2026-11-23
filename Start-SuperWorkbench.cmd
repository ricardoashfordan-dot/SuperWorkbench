@echo off
chcp 65001 >nul
where pythonw >nul 2>&1
if %errorlevel% equ 0 (
    start "" pythonw "%~dp0start.py" %*
) else (
    start "" /min python "%~dp0start.py" %*
)
