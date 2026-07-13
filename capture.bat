@echo off
cd /d "%~dp0"
REM CAN CHAY BANG PYTHON CUA ISAAC SIM:
REM   isaacsim\python.bat src\isaac_bev_capture.py %*
REM Neu da setup PATH Isaac Sim:
python src\isaac_bev_capture.py %*
if errorlevel 1 pause
