@echo off
cd /d "%~dp0"
REM PHAI CHAY BANG PYTHON CUA ISAAC SIM. Thu muc cai: bien ISAACSIM, mac dinh C:\isaacsim
REM   capture.bat AV_Steam        (1 prop + chan doan)
REM   capture.bat --library       (ca thu vien asset)
if "%ISAACSIM%"=="" set "ISAACSIM=C:\isaacsim"
if not exist "%ISAACSIM%\python.bat" (
    echo Khong tim thay Isaac Sim tai %ISAACSIM% - dat bien ISAACSIM.
    pause
    exit /b 1
)
REM Khong nap package trong AppData\Roaming\Python (numpy cai rieng se xung dot voi ban cua Isaac)
set PYTHONNOUSERSITE=1
call "%ISAACSIM%\python.bat" src\isaac_bev_capture.py %*
if errorlevel 1 pause
