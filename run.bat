@echo off
chcp 65001 >nul
cd /d "%~dp0"
call conda activate chan_py311
python main.py
pause
