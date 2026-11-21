@echo off
setlocal EnableDelayedExpansion
rem ssh key: override with env PI5_SSH_KEY, default %USERPROFILE%\.ssh\id_rsa_pi5 (Mac migration prep 2026-11-21)
if not defined PI5_SSH_KEY set PI5_SSH_KEY=%USERPROFILE%\.ssh\id_rsa_pi5
set KEY=%PI5_SSH_KEY%
set OUT=%~dp0pi_probe_out
set SSHOPT=-i %KEY% -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=6
del /q "%OUT%\DONE.flag" 2>nul
for %%H in (192.168.50.228 192.168.50.229) do (
  echo [%TIME%] probing %%H ...
  ssh %SSHOPT% pi@%%H bash -s < "%~dp0pi_probe_remote.sh" > "%OUT%\%%H.txt" 2>&1
  echo exit=!ERRORLEVEL! >> "%OUT%\%%H.txt"
)
echo done > "%OUT%\DONE.flag"
