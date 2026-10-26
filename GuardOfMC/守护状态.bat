@echo off
title MC 守护状态
echo ---- 守护进程 ----
tasklist /FI "IMAGENAME eq python.exe" | findstr /i python
echo.
echo ---- 最近日志 ----
powershell -NoProfile -Command "Get-Content 'D:\GuardOfMC\guard-log.txt' -Tail 8 -Encoding UTF8"
echo.
pause