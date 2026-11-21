@echo off
setlocal EnableDelayedExpansion
rem ssh key: override with env PI5_SSH_KEY, default %USERPROFILE%\.ssh\id_rsa_pi5 (Mac migration prep 2026-11-21)
if not defined PI5_SSH_KEY set PI5_SSH_KEY=%USERPROFILE%\.ssh\id_rsa_pi5
set KEY=%PI5_SSH_KEY%
set HOST=%~1
set SCRIPT=%~2
set OUT=%~dp0pi_probe_out
del /q "%OUT%\DONE.flag" 2>nul
ssh -i %KEY% -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=6 pi@%HOST% bash -s < "%~dp0%SCRIPT%" > "%OUT%\%HOST%_%~n2.txt" 2>&1
echo exit=!ERRORLEVEL! >> "%OUT%\%HOST%_%~n2.txt"
echo done > "%OUT%\DONE.flag"
