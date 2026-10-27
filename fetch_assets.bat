@echo off
cd /d "%~dp0"
python tools\fetch_office_assets.py %*
if errorlevel 1 pause
