#Requires -Version 7
<#
.SYNOPSIS
  Idempotent, non-interactive dev bootstrap for paperless-win (P1).

.DESCRIPTION
  Installs or locates the tools needed to run paperless-ngx natively on Windows and
  writes .tools\env.ps1, which prepends every tool folder to PATH for the current shell.

  Everything except uv, git and Node is unpacked under <repo>\.tools\ (no admin rights,
  nothing system-wide). Downloads are pinned and verified by SHA256.

  Usage:   pwsh windows/scripts/bootstrap-dev.ps1 [-SkipNode] [-WithOffice] [-Force]
  Then:    . .\.tools\env.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipNode,   # skip Node/pnpm (only needed to build the frontend)
    [switch]$WithOffice, # also unpack LibreOffice and fetch the Tika server (P8 tests; never part of the installer)
    [switch]$Force       # re-download and reinstall even if the tool is present
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest is ~10x faster without it

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Tools = Join-Path $RepoRoot '.tools'
$Dl = Join-Path $Tools 'dl'
New-Item -ItemType Directory -Force $Dl | Out-Null

# ---- pinned downloads -------------------------------------------------------------
$Manifest = Get-Content (Join-Path $PSScriptRoot '..\build\manifest.json') -Raw | ConvertFrom-Json
$Pins = @{}
foreach ($item in $Manifest.inputs) {
    if ($item.url) { $Pins[$item.id] = @{ File = $item.file; Url = $item.url; Sha = $item.sha256 } }
}

function Write-Step([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }

function Get-Pinned([string]$Name) {
    $pin = $Pins[$Name]
    $path = Join-Path $Dl $pin.File
    if (Test-Path $path) {
        if ((Get-FileHash $path -Algorithm SHA256).Hash.ToLower() -eq $pin.Sha) { return $path }
        Write-Warning "$($pin.File): cached file has wrong hash, re-downloading"
        Remove-Item $path -Force
    }
    Write-Host "    downloading $($pin.Url)"
    Invoke-WebRequest -Uri $pin.Url -OutFile $path -UseBasicParsing
    $actual = (Get-FileHash $path -Algorithm SHA256).Hash.ToLower()
    if ($actual -ne $pin.Sha) {
        Remove-Item $path -Force
        throw "SHA256 mismatch for $($pin.File): expected $($pin.Sha), got $actual"
    }
    return $path
}

function Test-Tool([string]$Exe) { return [bool](Test-Path $Exe) -and -not $Force }

function Install-WingetPackage([string]$Id, [string]$Cmd) {
    if (Get-Command $Cmd -ErrorAction SilentlyContinue) { Write-Host "    $Cmd found"; return }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { throw "$Cmd is missing and winget is not available; install $Id manually" }
    winget install --id $Id -e --silent --accept-source-agreements --accept-package-agreements | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "winget install $Id failed ($LASTEXITCODE)" }
}

# ---- uv, Python, git, Node ----------------------------------------------------------
Write-Step 'uv'
Install-WingetPackage 'astral-sh.uv' 'uv'
Write-Step 'Python 3.13 (via uv)'
uv python install 3.13
if ($LASTEXITCODE -ne 0) { throw 'uv python install failed' }
Write-Step 'git'
Install-WingetPackage 'Git.Git' 'git'
# ---- 7-Zip (unpacked from MSI) ------------------------------------------------------
# Tesseract and Ghostscript only ship as NSIS installers that ask for admin rights. We do
# not run them; we unpack their payload with 7-Zip into .tools\ instead.
Write-Step '7-Zip (for unpacking installers)'
$SevenZipDir = Join-Path $Tools '7zip'
$SevenZip = Join-Path $SevenZipDir 'Files\7-Zip\7z.exe'
if (-not (Test-Tool $SevenZip)) {
    $msi = Get-Pinned 'SevenZip'
    if (Test-Path $SevenZipDir) { Remove-Item $SevenZipDir -Recurse -Force }
    $p = Start-Process msiexec -ArgumentList '/a', "`"$msi`"", '/qn', "TARGETDIR=`"$SevenZipDir`"" -Wait -PassThru
    if ($p.ExitCode -ne 0 -or -not (Test-Path $SevenZip)) { throw "7-Zip unpack failed (exit $($p.ExitCode))" }
}
function Expand-Nsis([string]$Installer, [string]$Dest) {
    & $SevenZip x -y "-o$Dest" $Installer | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "7z failed unpacking $Installer" }
    Remove-Item (Join-Path $Dest '$PLUGINSDIR') -Recurse -Force -ErrorAction SilentlyContinue
}

# ---- Tesseract (NSIS payload unpacked to .tools) ----------------------------------
Write-Step 'Tesseract 5.4 + eng/deu'
$TessDir = Join-Path $Tools 'tesseract'
if (-not (Test-Tool (Join-Path $TessDir 'tesseract.exe'))) {
    $installer = Get-Pinned 'Tesseract'
    if (Test-Path $TessDir) { Remove-Item $TessDir -Recurse -Force }
    Expand-Nsis $installer $TessDir
    if (-not (Test-Path (Join-Path $TessDir 'tesseract.exe'))) { throw 'Tesseract unpack failed' }
}
$deuTarget = Join-Path $TessDir 'tessdata\deu.traineddata'
if (-not (Test-Path $deuTarget)) { Copy-Item (Get-Pinned 'TessDeu') $deuTarget }

# ---- Ghostscript ---------------------------------------------------------------------
Write-Step 'Ghostscript 10.08'
$GsDir = Join-Path $Tools 'ghostscript'
if (-not (Test-Tool (Join-Path $GsDir 'bin\gswin64c.exe'))) {
    $installer = Get-Pinned 'Ghostscript'
    if (Test-Path $GsDir) { Remove-Item $GsDir -Recurse -Force }
    Expand-Nsis $installer $GsDir
    if (-not (Test-Path (Join-Path $GsDir 'bin\gswin64c.exe'))) { throw 'Ghostscript unpack failed' }
}

# ---- Poppler, pngquant, Garnet (zip) -------------------------------------------------
function Expand-Pinned([string]$Name, [string]$Dest, [string]$Marker) {
    if (Test-Tool (Join-Path $Dest $Marker)) { return }
    $zip = Get-Pinned $Name
    if (Test-Path $Dest) { Remove-Item $Dest -Recurse -Force }
    Expand-Archive -Path $zip -DestinationPath $Dest -Force
}
Write-Step 'Poppler'
$PopplerDir = Join-Path $Tools 'poppler'
Expand-Pinned 'Poppler' $PopplerDir 'poppler-*\Library\bin\pdftoppm.exe'
Write-Step 'pngquant'
$PngquantDir = Join-Path $Tools 'pngquant'
Expand-Pinned 'Pngquant' $PngquantDir 'pngquant.exe'
Write-Step 'Garnet'
$GarnetDir = Join-Path $Tools 'garnet'
Expand-Pinned 'Garnet' $GarnetDir 'net10.0\GarnetServer.exe'
Write-Step 'Inno Setup (installer compiler)'
$InnoDir = Join-Path $Tools 'innosetup'
if (-not (Test-Tool (Join-Path $InnoDir 'ISCC.exe'))) {
    $inno = Get-Pinned 'InnoSetup'
    Start-Process $inno -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER', "/DIR=`"$InnoDir`"" -Wait
    if (-not (Test-Path (Join-Path $InnoDir 'ISCC.exe'))) { throw 'Inno Setup did not install (it should work without admin rights with /CURRENTUSER)' }
}
Write-Step 'WinSW (service wrapper)'
$WinSwDir = Join-Path $Tools 'winsw'
New-Item -ItemType Directory -Force $WinSwDir | Out-Null
Copy-Item (Get-Pinned 'WinSW') (Join-Path $WinSwDir 'WinSW-x64.exe') -Force

# ---- libmagic 5.48 (+ PCRE2) from conda-forge packages -----------------------------
# A .conda file is a zip holding a zstd-compressed tar; 7-Zip (unpacked above) reads both.
function Expand-Conda([string]$Package, [string]$Dest) {
    New-Item -ItemType Directory -Force $Dest | Out-Null
    & $SevenZip x -y "-o$Dest" $Package | Out-Null
    $zst = Get-ChildItem $Dest -Filter 'pkg-*.tar.zst' | Select-Object -First 1
    & $SevenZip x -y "-o$Dest" $zst.FullName | Out-Null
    $tar = Get-ChildItem $Dest -Filter '*.tar' | Select-Object -First 1
    & $SevenZip x -y "-o$Dest" $tar.FullName | Out-Null
}
Write-Step 'libmagic 5.48 (for python-magic)'
$LibMagicDir = Join-Path $Tools 'libmagic'
if (-not (Test-Tool (Join-Path $LibMagicDir 'libmagic-1.dll'))) {
    $tmp = Join-Path $Tools 'libmagic-unpack'
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    if (Test-Path $LibMagicDir) { Remove-Item $LibMagicDir -Recurse -Force }
    Expand-Conda (Get-Pinned 'LibMagic') (Join-Path $tmp 'libmagic')
    Expand-Conda (Get-Pinned 'Pcre2') (Join-Path $tmp 'pcre2')
    New-Item -ItemType Directory -Force $LibMagicDir | Out-Null
    # python-magic looks for libmagic-1.dll on PATH; the database is found through $env:MAGIC
    Copy-Item (Join-Path $tmp 'libmagic\Library\bin\libmagic.dll') (Join-Path $LibMagicDir 'libmagic-1.dll')
    Copy-Item (Join-Path $tmp 'libmagic\Library\share\misc\magic.mgc') (Join-Path $LibMagicDir 'magic.mgc')
    # libmagic imports pcre2-posix.dll, which imports pcre2-8.dll
    foreach ($dll in 'pcre2-posix.dll', 'pcre2-8.dll') { Copy-Item (Join-Path $tmp "pcre2\Library\bin\$dll") $LibMagicDir }
    Remove-Item $tmp -Recurse -Force
}
# ---- LibreOffice + Tika (only for the Office-document tests; the installer does not bundle them) ----
if ($WithOffice) {
    Write-Step 'LibreOffice (unpacked, no admin rights) and the Tika server'
    $LoDir = Join-Path $Tools 'libreoffice'
    if (-not (Test-Tool (Join-Path $LoDir 'program\soffice.exe'))) {
        if (Test-Path $LoDir) { Remove-Item $LoDir -Recurse -Force }
        $msi = Get-Pinned 'LibreOffice'
        # an administrative install image: msiexec /a only unpacks the files, it needs no elevation
        $p = Start-Process msiexec.exe -ArgumentList '/a', "`"$msi`"", '/qn', "TARGETDIR=`"$LoDir`"" -Wait -PassThru
        if ($p.ExitCode -ne 0 -or -not (Test-Path (Join-Path $LoDir 'program\soffice.exe'))) { throw "unpacking LibreOffice failed (msiexec exit code $($p.ExitCode))" }
    }
    $TikaDir = Join-Path $Tools 'tika'
    New-Item -ItemType Directory -Force $TikaDir | Out-Null
    Copy-Item (Get-Pinned 'Tika') (Join-Path $TikaDir $Pins['Tika'].File) -Force
}
# ---- Node 24 + pnpm (portable, only for building the frontend) ---------------------
$NodeDir = Join-Path $Tools 'node'
$PnpmVersion = '11.15.1'   # matches "packageManager" in src-ui/package.json
if (-not $SkipNode) {
    Write-Step "Node 24 + pnpm $PnpmVersion"
    if (-not (Test-Tool (Join-Path $NodeDir 'node.exe'))) {
        $zip = Get-Pinned 'Node'
        $tmp = Join-Path $Tools 'node-unpack'
        if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
        if (Test-Path $NodeDir) { Remove-Item $NodeDir -Recurse -Force }
        Expand-Archive -Path $zip -DestinationPath $tmp -Force
        Move-Item (Get-ChildItem $tmp -Directory | Select-Object -First 1).FullName $NodeDir
        Remove-Item $tmp -Recurse -Force
    }
    if (-not (Test-Path (Join-Path $NodeDir 'pnpm.cmd'))) {
        $env:PATH = "$NodeDir;$env:PATH"
        npm install --global --prefix $NodeDir "pnpm@$PnpmVersion" | Out-Host
        if ($LASTEXITCODE -ne 0) { throw 'npm install pnpm failed' }
    }
}
# ---- resolve actual binary folders (archives nest differently) ---------------------
function Find-Dir([string]$Root, [string]$Exe) {
    $hit = Get-ChildItem $Root -Recurse -Filter $Exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $hit) { throw "$Exe not found under $Root" }
    return $hit.DirectoryName
}
$dirs = [ordered]@{
    Tesseract = $TessDir
    Ghostscript = Join-Path $GsDir 'bin'
    Poppler   = Find-Dir $PopplerDir 'pdftoppm.exe'
    Pngquant  = Find-Dir $PngquantDir 'pngquant.exe'
    Garnet    = Find-Dir $GarnetDir 'GarnetServer.exe'
    LibMagic  = $LibMagicDir
}
if (-not $SkipNode) { $dirs.Node = $NodeDir }

# ---- env.ps1 ---------------------------------------------------------------------------
Write-Step 'Writing .tools\env.ps1'
$envFile = Join-Path $Tools 'env.ps1'
$lines = @('# Generated by windows/scripts/bootstrap-dev.ps1; do not edit.', '# Usage: . .\.tools\env.ps1')
foreach ($d in $dirs.Values) { $lines += "`$env:PATH = '$d;' + `$env:PATH" }
$lines += "`$env:TESSDATA_PREFIX = '$(Join-Path $TessDir 'tessdata')'"
$lines += "`$env:MAGIC = '$(Join-Path $LibMagicDir 'magic.mgc')'"
Set-Content -Path $envFile -Value $lines -Encoding utf8
. $envFile

# ---- verify ---------------------------------------------------------------------------
Write-Step 'Verifying'
$ok = $true
function Check([string]$Label, [scriptblock]$Cmd) {
    try { $out = (& $Cmd 2>&1 | Select-Object -First 1) -join ''; Write-Host ("    {0,-12} {1}" -f $Label, $out) }
    catch { Write-Host ("    {0,-12} FAILED: {1}" -f $Label, $_) -ForegroundColor Red; $script:ok = $false }
}
Check 'uv' { uv --version }
Check 'tesseract' { tesseract --version }
Check 'languages' { (tesseract --list-langs | Where-Object { $_ -in 'eng', 'deu' }) -join ',' }
Check 'ghostscript' { gswin64c --version }
Check 'pdftoppm' { pdftoppm -v }
Check 'pngquant' { pngquant --version }
Check 'garnet' { (Get-Item (Join-Path $dirs.Garnet 'GarnetServer.exe')).VersionInfo.ProductVersion }
Check 'iscc' { (Get-Item (Join-Path $InnoDir 'ISCC.exe')).VersionInfo.ProductVersion }
Check 'winsw' { (Get-Item (Join-Path $WinSwDir 'WinSW-x64.exe')).VersionInfo.ProductVersion }
if (-not $SkipNode) { Check 'node' { node --version }; Check 'pnpm' { pnpm --version } }
if (-not $ok) { throw 'bootstrap finished with errors' }
Write-Host "`nDone. In each new shell run:  . .\.tools\env.ps1" -ForegroundColor Green
