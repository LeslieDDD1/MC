@echo off
title MC 安装守护计划任务
schtasks /Create /F /TN "MC Guard Kicker" /SC MINUTE /MO 10 /TR "wscript.exe D:\GuardOfMC\mc-guard-hidden.vbs"
schtasks /Run /TN "MC Guard Kicker"
echo.
echo 已注册并启动守护计划任务(每10分钟自动保活, 开机后10分钟内自动运行)
pause