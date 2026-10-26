@echo off
title MC 启动守护
wscript.exe D:\GuardOfMC\mc-guard-hidden.vbs
echo 守护已启动(若已在运行则无变化)。
timeout /t 5 >nul