#Requires -Version 7
<#
.SYNOPSIS
  Idempotent, non-interactive dev bootstrap for paperless-win (P1).

.DESCRIPTION
  Installs or locates the tools needed to run paperless-ngx natively on Windows and
  writes .tools\env.ps1, which prepends every tool folder to PATH for the current shell.

  Everything except uv, git and Node is unpacked under <repo>\.tools\ (no admin rights,
  nothing system-wide). Downloads are pinned and verified by SHA256.

  Usage:   pwsh windows/scripts/bootstrap-dev.ps1 [-SkipNode] [-Force]
  Then:    . .\.tools\env.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipNode,   # skip Node/pnpm (only needed to build the frontend)
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
$Pins = @{
    SevenZip = @{
        # MSI is only unpacked (msiexec /a), never installed: no admin rights needed.
        File = '7z2606-x64.msi'
        Url  = 'https://github.com/ip7z/7zip/releases/download/26.06/7z2606-x64.msi'
        Sha  = '6dc822569e777d9a3ecd5ffcbc22b55600af87e6c5d9810a64e8566cf5a4af9f'
    }
    Node = @{
        # Angular 21 needs Node >= 22.22.3 or >= 24.15; upstream's Dockerfile builds with Node 24.
        File = 'node-v24.22.3-win-x64.zip'
        Url  = 'https://nodejs.org/dist/v24.22.3/node-v24.22.3-win-x64.zip'
        Sha  = 'e612af99f626ab415ea225af6bce5c971feb448cb5cae250bb1c3fa50c5f7d9f'
    }
    LibMagic = @{
        # python-magic needs libmagic. We take only the DLL + magic database from this wheel
        # (the wheel's own magic.py is old and cannot handle pathlib.Path; keep python-magic).
        File = 'python_magic_bin-0.4.14-py2.py3-none-win_amd64.whl'
        Url  = 'https://files.pythonhosted.org/packages/07/c2/094e3d62b906d952537196603a23aec4bcd7c6126bf80eb14e6f9f4be3a2/python_magic_bin-0.4.14-py2.py3-none-win_amd64.whl'
        Sha  = '90be6206ad31071a36065a2fc169c5afb5e0355cbe6030e87641c6c62edc2b69'
    }
    Tesseract = @{
        File = 'tesseract-ocr-w64-setup-5.4.0.20240606.exe'
        Url  = 'https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/tesseract-ocr-w64-setup-5.4.0.20240606.exe'
        Sha  = 'c885fff6998e0608ba4bb8ab51436e1c6775c2bafc2559a19b423e18678b60c9'
    }
    TessDeu = @{
        File = 'deu.traineddata'
        Url  = 'https://github.com/tesseract-ocr/tessdata_fast/raw/refs/heads/main/deu.traineddata'
        Sha  = '19d219bbb6672c869d20a9636c6816a81eb9a71796cb93ebe0cb1530e2cdb22d'
    }
    Ghostscript = @{
        File = 'gs10080w64.exe'
        Url  = 'https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs10080/gs10080w64.exe'
        Sha  = '52a91b8bf09298788d7a57b9206127026c23eacd75405f0a131e26dc381dce50'
    }
    Poppler = @{
        File = 'poppler-26.09.0-0.zip'
        Url  = 'https://github.com/oschwartz10612/poppler-windows/releases/download/v26.09.0-0/Release-26.09.0-0.zip'
        Sha  = '7a6f256a0ddf7536182246a5733331bf4677cbcc34f4663774947ad34556c8d0'
    }
    Pngquant = @{
        # pngquant.org serves an unversioned URL; if this hash stops matching, review and re-pin.
        File = 'pngquant-windows.zip'
        Url  = 'https://pngquant.org/pngquant-windows.zip'
        Sha  = 'bd0257aeeccfe446a4cd764927e26f8af6051796f28abed104307284107b120d'
    }
    Garnet = @{
        File = 'garnet-2.2.13-win-x64.zip'
        Url  = 'https://github.com/microsoft/garnet/releases/download/v2.2.13/win-x64-based-readytorun.zip'
        Sha  = 'cc8212d7c7a671c490e5c87967fc43025a22215922bdbdad5eccff00915c7b82'
    }
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

# ---- libmagic (DLL + database only) ------------------------------------------------
Write-Step 'libmagic (for python-magic)'
$LibMagicDir = Join-Path $Tools 'libmagic'
if (-not (Test-Tool (Join-Path $LibMagicDir 'libmagic-1.dll'))) {
    $whl = Get-Pinned 'LibMagic'
    $tmp = Join-Path $Tools 'libmagic-unpack'
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    [IO.Compression.ZipFile]::ExtractToDirectory($whl, $tmp)   # a .whl is a zip, but Expand-Archive insists on .zip
    New-Item -ItemType Directory -Force $LibMagicDir | Out-Null
    # python-magic looks for libmagic-1.dll on PATH; the database is found through $env:MAGIC
    Copy-Item (Join-Path $tmp 'magic\libmagic\libmagic.dll') (Join-Path $LibMagicDir 'libmagic-1.dll') -Force
    Copy-Item (Join-Path $tmp 'magic\libmagic\magic.mgc') (Join-Path $LibMagicDir 'magic.mgc') -Force
    Remove-Item $tmp -Recurse -Force
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
if (-not $SkipNode) { Check 'node' { node --version }; Check 'pnpm' { pnpm --version } }
if (-not $ok) { throw 'bootstrap finished with errors' }
Write-Host "`nDone. In each new shell run:  . .\.tools\env.ps1" -ForegroundColor Green







