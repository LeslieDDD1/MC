@echo off
title MC 快照管理
echo.
echo ==================== MC 世界快照 ====================
powershell -NoProfile -File D:\GuardOfMC\mc-rollback.ps1
echo.
echo 恢复快照(需先关闭游戏):
echo   powershell -File D:\GuardOfMC\mc-rollback.ps1 -Restore 0
echo   (0=最新一份, 1=前一份, 以此类推)
echo.
pause