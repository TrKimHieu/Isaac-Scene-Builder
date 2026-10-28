@echo off
cd /d "%~dp0"
python tools\check_density_distribution.py %*
if errorlevel 1 pause
