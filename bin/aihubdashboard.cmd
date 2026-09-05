@echo off
rem Mo dashboard AI Hub. Vo bao boc mong quanh aihubdashboard.ps1 -
rem toan bo logic nam trong file .ps1 de duong dan co dau cach khong bi tach.

setlocal
if "%AIHUB_HOME%"=="" (
  for %%I in ("%~dp0..") do set "AIHUB_HOME=%%~fI"
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0aihubdashboard.ps1" %*
exit /b %ERRORLEVEL%
