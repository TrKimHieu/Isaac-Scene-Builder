@echo off
cd /d "%~dp0"
python src\shape_editor.py %*
if errorlevel 1 pause
