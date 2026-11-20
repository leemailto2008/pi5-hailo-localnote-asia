# 從盒子拉回全部 Issue 回報（網頁「🐞 Issue 回報」存的），解壓到 .cc_scratch\feedback\<主機>_<時間>\
# 用法：powershell -File tools\pull_feedback.ps1 [-Box 192.168.50.228] [-Port 8000]
param(
    [string]$Box = "192.168.50.228",
    [int]$Port = 8000
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$outDir = Join-Path $root ".cc_scratch\feedback\${Box}_$stamp"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$zip = Join-Path $outDir "feedback.zip"
try {
    Invoke-WebRequest -Uri "http://${Box}:${Port}/api/feedback/export.zip" -OutFile $zip -UseBasicParsing -TimeoutSec 120
} catch {
    Write-Error "下載失敗（盒子 $Box 連得上嗎？）：$($_.Exception.Message)"
    exit 1
}
Expand-Archive -Path $zip -DestinationPath $outDir -Force
$n = (Get-ChildItem -Directory $outDir).Count
Write-Output "拉回 $n 筆回報 → $outDir"
