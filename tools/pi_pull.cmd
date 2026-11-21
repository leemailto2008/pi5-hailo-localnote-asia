@echo off
setlocal EnableDelayedExpansion
rem ssh key: override with env PI5_SSH_KEY, default %USERPROFILE%\.ssh\id_rsa_pi5 (Mac migration prep 2026-11-21)
if not defined PI5_SSH_KEY set PI5_SSH_KEY=%USERPROFILE%\.ssh\id_rsa_pi5
set KEY=%PI5_SSH_KEY%
set OUT=%~dp0pi_probe_out
del /q "%OUT%\DONE.flag" 2>nul
if not "%~4"=="" (
  ssh -i %KEY% -o BatchMode=yes -o ConnectTimeout=6 pi@%~1 bash -s < "%~dp0%~4" > "%OUT%\%~1_%~n4.txt" 2>&1
  echo exit=!ERRORLEVEL! >> "%OUT%\%~1_%~n4.txt"
)
scp -i %KEY% -o BatchMode=yes -o ConnectTimeout=6 pi@%~1:"%~2" "%~3" > "%OUT%\%~1_pull.txt" 2>&1
echo exit=!ERRORLEVEL! >> "%OUT%\%~1_pull.txt"
echo done > "%OUT%\DONE.flag"
