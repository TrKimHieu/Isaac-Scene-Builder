@echo off
cd /d "%~dp0"
python src\scene_editor.py %*
if errorlevel 1 pause
