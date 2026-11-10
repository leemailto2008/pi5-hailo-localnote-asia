@echo off
setlocal EnableDelayedExpansion
set KEY=C:\Users\Andrew\.ssh\id_rsa_pi5
set OUT=%~dp0pi_probe_out
del /q "%OUT%\DONE.flag" 2>nul
if not "%~4"=="" (
  ssh -i %KEY% -o BatchMode=yes -o ConnectTimeout=6 pi@%~1 bash -s < "%~dp0%~4" > "%OUT%\%~1_%~n4.txt" 2>&1
  echo exit=!ERRORLEVEL! >> "%OUT%\%~1_%~n4.txt"
)
scp -i %KEY% -o BatchMode=yes -o ConnectTimeout=6 pi@%~1:"%~2" "%~3" > "%OUT%\%~1_pull.txt" 2>&1
echo exit=!ERRORLEVEL! >> "%OUT%\%~1_pull.txt"
echo done > "%OUT%\DONE.flag"
