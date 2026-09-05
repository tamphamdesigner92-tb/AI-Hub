@echo off
rem AI Hub CLI cho Windows.
rem
rem Chay bang venv rieng cua hub neu co, de `aihub pull` khong phu thuoc vao
rem venv cua du an dang mo. Khong co thi dung python trong PATH.
rem
rem Goi thang module bang -c thay vi cai package: aihub chay duoc ngay sau khi
rem clone, khong can buoc pip install nao.

setlocal
if "%AIHUB_HOME%"=="" (
  for %%I in ("%~dp0..") do set "AIHUB_HOME=%%~fI"
)

set "PY=%AIHUB_HOME%\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" -c "import sys; sys.path.insert(0, r'%AIHUB_HOME%\clients\python\src'); from aihub.cli import main; sys.exit(main())" %*
exit /b %ERRORLEVEL%
