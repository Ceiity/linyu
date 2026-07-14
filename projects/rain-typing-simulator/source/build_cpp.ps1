$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent $root
$outputs = Join-Path $repo "outputs"
New-Item -ItemType Directory -Force -Path $outputs | Out-Null
$out = Join-Path $outputs "$([char]0x6DCB)$([char]0x96E8).exe"

$clang = Get-Command clang++.exe -ErrorAction SilentlyContinue
$windres = Get-Command windres.exe -ErrorAction SilentlyContinue

if (-not $clang -or -not $windres) {
    $pkgRoot = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    $clangPath = Get-ChildItem $pkgRoot -Recurse -Filter clang++.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
    $windresPath = Get-ChildItem $pkgRoot -Recurse -Filter windres.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
} else {
    $clangPath = $clang.Source
    $windresPath = $windres.Source
}

if (-not $clangPath -or -not $windresPath) {
    throw "LLVM-MinGW was not found. Install MartinStorsjo.LLVM-MinGW.UCRT with winget first."
}

& $windresPath (Join-Path $root "resource.rc") -O coff -o (Join-Path $root "resource.o")
if ($LASTEXITCODE -ne 0) {
    throw "Resource compile failed with exit code $LASTEXITCODE."
}

& $clangPath -std=c++17 -O2 -municode -mwindows -static `
    (Join-Path $root "main.cpp") (Join-Path $root "resource.o") `
    -o $out -lcomctl32 -lpsapi -lwinmm -lshell32 -lcomdlg32 -ldwmapi -lgdi32 -lgdiplus -lole32 -ladvapi32 -lwinhttp -liphlpapi -limm32
if ($LASTEXITCODE -ne 0) {
    throw "C++ compile failed with exit code $LASTEXITCODE."
}

Write-Host "Built: $out"

# ========== 自动签名 ==========
Write-Host "Signing with self-signed certificate..."
$cert = Get-ChildItem Cert:\CurrentUser\My | Where-Object { $_.Subject -match "淋雨|Seagull" } | Select-Object -First 1
if ($cert) {
    Set-AuthenticodeSignature -Certificate $cert -FilePath $out -TimestampServer "http://timestamp.digicert.com" | Out-Null
    Write-Host "Signed: $out"
} else {
    Write-Host "WARNING: No signing cert found. Build unsigned."
}
