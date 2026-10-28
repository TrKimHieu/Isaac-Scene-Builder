@echo off
cd /d "%~dp0"
python tools\batch_generate_scenes.py %*
if errorlevel 1 pause
