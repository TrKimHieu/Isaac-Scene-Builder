@echo off
cd /d "%~dp0"
python src\build_furniture_shapes.py %*
if errorlevel 1 pause
