@echo off
title MC 恢复快照
echo ============================================
echo  即将把世界恢复到最新一份快照!
echo  当前世界会被替换(旧世界自动挪到 quarantine)
echo ============================================
choice /c YN /m "游戏已经关闭了吗? 按Y恢复, 按N取消"
if errorlevel 2 goto end
powershell -NoProfile -File D:\GuardOfMC\mc-rollback.ps1 -Restore 0
:end
echo.
pause