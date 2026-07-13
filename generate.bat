@echo off
cd /d "%~dp0"
python src\generate_scene.py %*
if errorlevel 1 pause
