#Requires -Version 7
<#
.SYNOPSIS
  Build dist\paperless-win-setup-<version>.exe from a clean checkout.

.DESCRIPTION
  1. tools      windows\scripts\bootstrap-dev.ps1 (every input is pinned and checksummed in
                windows\build\manifest.json)
  2. frontend   pnpm install --frozen-lockfile, production build of the Angular app
  3. python     the standalone CPython, plus a wheelhouse of every dependency from uv.lock
                (`uv export` + `pip wheel`, with hashes: the build fails if a wheel changes)
  4. stage      dist\stage\app\  = python, src, bin\<tool>, service, wheelhouse, uv, licences
  5. hash list  dist\app-hashes-<version>.txt: path and SHA-256 of every staged file. Two builds of
                the same commit must produce identical lists (timestamps are not compared).
  6. installer  Inno Setup compiles windows\installer\paperless-win.iss

  The staged app has no venv: the installer creates it on the target machine from the bundled
  wheelhouse, offline. -IncludeAiLocal also builds the wheelhouse of the optional Local AI add-on
  (torch and friends, several hundred MB) into dist\paperless-win-ai-local-<version>.zip.

  Code signing is not part of v0.1.0. Set SIGN_COMMAND to a signtool command line containing
  $f to sign the installer; it is run once after compiling.
#>
[CmdletBinding()]
param(
    [string]$Version = '0.1.0-dev',
    [string]$OutDir = '',
    [switch]$SkipBootstrap,
    [switch]$SkipFrontend,     # use the frontend already built into src\documents\static\frontend
    [switch]$SkipInstaller,    # stop after staging and the hash list
    [switch]$IncludeAiLocal,
    [switch]$FastCompression   # quick, larger installer for testing
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$repo = (Resolve-Path "$PSScriptRoot\..\..").Path
$tools = Join-Path $repo '.tools'
$cache = Join-Path $tools 'dl'
if (-not $OutDir) { $OutDir = Join-Path $repo 'dist' }
$stageRoot = Join-Path $OutDir 'stage'
$app = Join-Path $stageRoot 'app'
$work = Join-Path $OutDir 'work'
$manifest = Get-Content "$PSScriptRoot\manifest.json" -Raw | ConvertFrom-Json
function Write-Step([string]$m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Get-Input([string]$id) { $manifest.inputs | Where-Object id -eq $id | Select-Object -First 1 }
function Get-Cached([string]$id) {
    # the pinned download for a manifest input: from the cache, or downloaded and verified now
    $i = Get-Input $id
    New-Item -ItemType Directory -Force $cache | Out-Null
    $path = Join-Path $cache $i.file
    if (Test-Path $path) {
        if ((Get-FileHash $path -Algorithm SHA256).Hash.ToLower() -eq $i.sha256) { return $path }
        Write-Warning "$($i.file): cached file has the wrong hash, downloading again"
        Remove-Item $path -Force
    }
    Write-Host "    downloading $($i.url)"
    Invoke-WebRequest -Uri $i.url -OutFile $path -UseBasicParsing
    $actual = (Get-FileHash $path -Algorithm SHA256).Hash.ToLower()
    if ($actual -ne $i.sha256) {
        Remove-Item $path -Force
        throw "SHA256 mismatch for $($i.file): expected $($i.sha256), got $actual"
    }
    return $path
}
function Copy-Tree([string]$From, [string]$To, [string[]]$ExcludeDirs = @(), [string[]]$ExcludeFiles = @()) {
    New-Item -ItemType Directory -Force $To | Out-Null
    $args2 = @($From, $To, '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:2', '/W:1')
    if ($ExcludeDirs) { $args2 += '/XD'; $args2 += $ExcludeDirs }
    if ($ExcludeFiles) { $args2 += '/XF'; $args2 += $ExcludeFiles }
    robocopy @args2 | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy $From -> $To failed ($LASTEXITCODE)" }
    $global:LASTEXITCODE = 0
}

# --- 1. tools -------------------------------------------------------------------------------------------------------------------
if (-not $SkipBootstrap) {
    Write-Step 'Tools (pinned, checksummed)'
    $bootstrapArgs = @()
    if ($SkipFrontend) { $bootstrapArgs += '-SkipNode' }
    & "$repo\windows\scripts\bootstrap-dev.ps1" @bootstrapArgs
}
. "$tools\env.ps1"

# --- 2. frontend ----------------------------------------------------------------------------------------------------------------------
$frontend = Join-Path $repo 'src\documents\static\frontend'
if ($SkipFrontend) {
    if (-not (Test-Path "$frontend\en-US\index.html")) { throw "-SkipFrontend, but $frontend has no build" }
    Write-Step "Frontend: reusing $frontend"
}
else {
    Write-Step 'Frontend (pnpm install --frozen-lockfile; production build)'
    Push-Location "$repo\src-ui"
    try {
        pnpm install --frozen-lockfile
        if ($LASTEXITCODE -ne 0) { throw 'pnpm install failed' }
        pnpm run build --configuration production
        if ($LASTEXITCODE -ne 0) { throw 'frontend build failed' }
    }
    finally { Pop-Location }
}

# --- 3. clean staging, python, wheelhouse -----------------------------------------------------------------------------
Write-Step "Staging in $stageRoot"
if (Test-Path $stageRoot) { Remove-Item $stageRoot -Recurse -Force }
if (Test-Path $work) { Remove-Item $work -Recurse -Force }
New-Item -ItemType Directory -Force $app, $work | Out-Null

Write-Step 'CPython (python-build-standalone)'
& "$env:SystemRoot\System32\tar.exe" -xzf (Get-Cached 'Python') -C $app   # not Git's GNU tar: it reads 'C:' as a host name
if (-not (Test-Path "$app\python\python.exe")) { throw 'the CPython archive did not unpack to python\python.exe' }
$py = "$app\python\python.exe"
Write-Host "    $(& $py --version)"

function Export-Requirements([string]$Path, [string[]]$Extras) {
    $a = @('export', '--frozen', '--no-dev', '--no-emit-project', '--no-header', '--format', 'requirements-txt', '--output-file', $Path)
    foreach ($e in $Extras) { $a += '--extra'; $a += $e }
    Push-Location $repo
    try { uv @a | Out-Null; if ($LASTEXITCODE -ne 0) { throw "uv export failed ($Extras)" } } finally { Pop-Location }
}
function Get-Wheels([string]$Requirements, [string]$Dest) {
    # `pip wheel` downloads every wheel (hashes from uv.lock are enforced) and builds the few
    # source-only packages into wheels. The build tools are pinned and SOURCE_DATE_EPOCH is fixed,
    # so those wheels are identical from build to build.
    New-Item -ItemType Directory -Force $Dest | Out-Null
    $env:PIP_CONSTRAINT = "$PSScriptRoot\build-constraints.txt"
    $env:SOURCE_DATE_EPOCH = (git -C $repo log -1 --format=%ct).Trim()
    try {
        & $py -m pip wheel -r $Requirements -w $Dest --no-deps --disable-pip-version-check --quiet
        if ($LASTEXITCODE -ne 0) { throw "pip wheel failed for $Requirements" }
    }
    finally { Remove-Item Env:PIP_CONSTRAINT, Env:SOURCE_DATE_EPOCH -ErrorAction SilentlyContinue }
}
Write-Step 'Wheelhouse: base (uv.lock, hashes enforced)'
# mariadb is left out on purpose: mysqlclient has no Windows wheel (see windows/tasks/10-packaging-installer.md)
Export-Requirements "$work\requirements-base.txt" @('webserver', 'postgres')
Get-Wheels "$work\requirements-base.txt" "$app\wheelhouse\base"
# install-time list: pinned versions without hashes (wheels built from source have none in uv.lock;
# every download was hash-verified above and the wheelhouse ships inside the installer)
$plain = @('export', '--frozen', '--no-dev', '--no-emit-project', '--no-header', '--no-hashes', '--format', 'requirements-txt', '--output-file', "$app\requirements.txt", '--extra', 'webserver', '--extra', 'postgres')
Push-Location $repo; try { uv @plain | Out-Null; if ($LASTEXITCODE -ne 0) { throw 'uv export (no hashes) failed' } } finally { Pop-Location }
Write-Host "    $((Get-ChildItem "$app\wheelhouse\base" -File | Measure-Object).Count) wheels, $([math]::Round((Get-ChildItem "$app\wheelhouse\base" -File | Measure-Object Length -Sum).Sum / 1MB)) MB"

# --- 4. application files --------------------------------------------------------------------------------------------------------
Write-Step 'Application source'
Copy-Tree "$repo\src" "$app\src" -ExcludeDirs @('tests', '__pycache__', '.pytest_cache', 'samples') -ExcludeFiles @('*.pyc', '*.po', '*.pot')
Copy-Item "$repo\windows\assets" "$app\assets" -Recurse
Copy-Tree "$repo\windows\examples" "$app\examples"
Copy-Item "$repo\LICENSE" "$app\LICENSE.txt"
Copy-Item "$repo\windows\THIRD_PARTY.md" "$app\THIRD_PARTY.md"
Copy-Item "$repo\windows\SERVICE.md" "$app\SERVICE.md"
Set-Content "$app\VERSION" $Version -NoNewline -Encoding ascii
@"
paperless-win is an UNOFFICIAL port of paperless-ngx to Windows. It is not made, endorsed or
supported by the paperless-ngx project or its contributors: please do not ask them for help
with it, and report problems at https://github.com/VikoPiko/paperless-win/issues instead.

paperless-win is free software under the GNU General Public License, version 3, like
paperless-ngx. It also contains third-party programs under their own licences (see
THIRD_PARTY.md in the installation folder). This installer is not code-signed yet, so Windows
SmartScreen may warn before it starts: choose "More info", then "Run anyway".

------------------------------------------------------------------------------------------

"@ + (Get-Content "$repo\LICENSE" -Raw) | Set-Content "$stageRoot\LICENSE-installer.txt" -Encoding utf8

Write-Step 'Tools: Tesseract, Ghostscript, Poppler, pngquant, Garnet, libmagic'
$bin = "$app\bin"
# Tesseract: the OCR engine and its DLLs, not the training tools or HTML manuals
$tess = "$bin\tesseract"
New-Item -ItemType Directory -Force "$tess\tessdata" | Out-Null
Copy-Item "$tools\tesseract\tesseract.exe", "$tools\tesseract\*.dll" $tess
Copy-Item "$tools\tesseract\tessdata\eng.traineddata", "$tools\tesseract\tessdata\osd.traineddata", "$tools\tesseract\tessdata\pdf.ttf" "$tess\tessdata"
Copy-Tree "$tools\tesseract\tessdata\configs" "$tess\tessdata\configs"
# more languages: the installer copies the selected ones next to eng
$langDir = "$app\tessdata-extra"
New-Item -ItemType Directory -Force $langDir | Out-Null
foreach ($l in ($manifest.inputs | Where-Object { $_.PSObject.Properties.Name -contains 'lang' })) {
    Copy-Item (Get-Cached $l.id) (Join-Path $langDir "$($l.lang).traineddata")
}
Copy-Tree "$tools\ghostscript" "$bin\ghostscript" -ExcludeDirs @('doc', 'examples') -ExcludeFiles @('vcredist_x64.exe', 'uninstgs.exe.nsis')
Copy-Tree (Get-ChildItem "$tools\poppler" -Directory | Select-Object -First 1).FullName "$bin\poppler" -ExcludeDirs @('include', 'doc')
Copy-Tree "$tools\pngquant" "$bin\pngquant"
Copy-Tree "$tools\garnet" "$bin\garnet"
Copy-Tree "$tools\libmagic" "$bin\libmagic"

Write-Step 'Service wrapper, uv, launcher'
New-Item -ItemType Directory -Force "$app\service" | Out-Null
Copy-Item (Get-Cached 'WinSW') "$app\service\paperless-win-service.exe"
$uvZip = Get-Cached 'Uv'
Expand-Archive $uvZip "$work\uv" -Force
Copy-Item (Get-ChildItem "$work\uv" -Recurse -Filter uv.exe | Select-Object -First 1).FullName "$app\uv.exe"
@'
@echo off
rem paperless-ctl: control paperless-win (run "paperless-ctl --help").
setlocal
set "PYTHONPATH=%~dp0src"
set "PYTHONUTF8=1"
"%~dp0venv\Scripts\python.exe" -m paperless_win %*
exit /b %ERRORLEVEL%
'@ | Set-Content "$app\paperless-ctl.cmd" -Encoding ascii

# --- 5. the Local AI add-on -------------------------------------------------------------------------------------------------------
# The requirements file is small and ships inside the installer: the "Local AI" task installs from it
# over the network. The wheels themselves are only built with -IncludeAiLocal (a separate download).
Write-Step 'Local AI add-on requirements'
Export-Requirements "$work\requirements-all.txt" @('webserver', 'postgres', 'ai-local')
& $py "$PSScriptRoot\split_requirements.py" "$work\requirements-base.txt" "$work\requirements-all.txt" "$app\requirements-ai-local.txt" --extra-index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) { throw 'splitting the ai-local requirements failed' }
if ($IncludeAiLocal) {
    Write-Step 'Wheelhouse: ai-local (torch and friends; large)'
    Get-Wheels "$app\requirements-ai-local.txt" "$work\ai-local\wheelhouse"
    Copy-Item "$app\requirements-ai-local.txt" "$work\ai-local\requirements-ai-local.txt"
    $zip = Join-Path $OutDir "paperless-win-ai-local-$Version.zip"
    if (Test-Path $zip) { Remove-Item $zip }
    Compress-Archive "$work\ai-local\*" $zip -CompressionLevel Optimal
    Write-Host "    $zip ($([math]::Round((Get-Item $zip).Length / 1MB)) MB)"
}

# running the staged Python (pip) left bytecode behind; it differs from run to run and the app compiles its own at init
Get-ChildItem $app -Recurse -Directory -Filter __pycache__ -Force | Remove-Item -Recurse -Force

# --- 6. hash list (reproducibility check) ---------------------------------------------------------------------------------
Write-Step 'Hash list'
$hashFile = Join-Path $OutDir "app-hashes-$Version.txt"
$appPrefix = $app.TrimEnd('\') + '\'
$lines = Get-ChildItem $app -Recurse -File -Force | ForEach-Object {
    "{0}`t{1}" -f $_.FullName.Substring($appPrefix.Length).Replace('\', '/'), (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
}
[array]::Sort($lines, [StringComparer]::Ordinal)
Set-Content $hashFile $lines -Encoding utf8
$stageMB = [math]::Round((Get-ChildItem $app -Recurse -File | Measure-Object Length -Sum).Sum / 1MB)
Write-Host "    $($lines.Count) files, $stageMB MB staged; list: $hashFile"

if ($SkipInstaller) { Write-Host 'Stopping before the installer (-SkipInstaller).'; exit 0 }

# --- 7. installer ----------------------------------------------------------------------------------------------------------------------------------
Write-Step 'Installer (Inno Setup)'
$iscc = Join-Path $tools 'innosetup\ISCC.exe'
if (-not (Test-Path $iscc)) { throw 'ISCC.exe not found: run windows\scripts\bootstrap-dev.ps1' }
$isccArgs = @("/Q", "/DAppVersion=$Version", "/DStageDir=$app", "/DOutputDir=$OutDir")
if ($FastCompression) { $isccArgs += "/DCompression=lzma2/fast" }
& $iscc @isccArgs "$repo\windows\installer\paperless-win.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed ($LASTEXITCODE)" }
$setup = Join-Path $OutDir "paperless-win-setup-$Version.exe"
if ($env:SIGN_COMMAND) {
    Write-Step 'Signing'
    $cmd = $env:SIGN_COMMAND.Replace('$f', "`"$setup`"")
    Invoke-Expression $cmd
    if ($LASTEXITCODE -ne 0) { throw 'signing failed' }
}
$size = [math]::Round((Get-Item $setup).Length / 1MB)
Write-Host "`nBuilt $setup ($size MB)" -ForegroundColor Green
Write-Host "SHA256 $((Get-FileHash $setup -Algorithm SHA256).Hash.ToLower())"
