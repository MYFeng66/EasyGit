@echo off
rem EasyGit launcher: double-click to start
cd /d "%~dp0"
chcp 65001 >nul
".venv\Scripts\python.exe" -m easygit
if errorlevel 1 pause
