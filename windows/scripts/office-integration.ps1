#Requires -Version 7
<#
.SYNOPSIS
  Integration test for Office documents and e-mail (P8): Tika, LibreOffice and Edge behind paperless.

.DESCRIPTION
  Needs LibreOffice, a Tika server jar and Java (`bootstrap-dev.ps1 -WithOffice` fetches the first two;
  Java and Edge come with the computer or CI image). Uses its own data folder and ports; nothing of an
  installed paperless-win is touched. Steps:

    1. `paperless-ctl check` sees Tika, LibreOffice and a browser.
    2. DOCX, ODT, XLSX, PPTX and an HTML e-mail dropped into the consume folder become documents with an
       archive PDF whose text contains the known word.
    3. 20 distinct DOCX files uploaded at the same moment all become documents, nothing fails, and no
       soffice process is left behind.
    4. Without LibreOffice a document fails with a message that says what to install.

  Exit code 0 = passed, 1 = a check failed, 2 = bad setup.
#>
[CmdletBinding()]
param(
    [string]$Python = '',
    [string]$Java = '',
    [int]$WebPort = 8012,
    [int]$BrokerPort = 6392,
    [string]$StaticFrom = '',
    [int]$Batch = 20,
    [switch]$Keep
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
if (-not $Python) { $Python = Join-Path $root '.venv\Scripts\python.exe' }
if (-not (Test-Path $Python)) { Write-Error "python not found: $Python"; exit 2 }
if (-not $Java) { $Java = (Get-Command java -ErrorAction SilentlyContinue)?.Source }
if (-not $Java) { Write-Error 'No Java runtime found (needed by the Tika server): install one or pass -Java.'; exit 2 }
$fixtures = Join-Path $root 'windows\fixtures\office'
if (-not (Test-Path "$fixtures\office-text.docx")) { Write-Error "fixtures missing in $fixtures"; exit 2 }

# --- own environment ---------------------------------------------------------------------------------------------
Get-ChildItem Env: | Where-Object { $_.Name -like 'PAPERLESS_*' } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
$work = Join-Path $env:TEMP 'paperless-office-integration'
if (Test-Path $work) { Remove-Item $work -Recurse -Force }
New-Item -ItemType Directory -Force $work | Out-Null
$env:PAPERLESS_DATA_DIR = "$work\data"; $env:PAPERLESS_MEDIA_ROOT = "$work\media"; $env:PAPERLESS_CONSUMPTION_DIR = "$work\consume"
$env:PAPERLESS_STATICDIR = "$work\static"; $env:PAPERLESS_SCRATCH_DIR = "$work\scratch"; $env:PAPERLESS_LOGGING_DIR = "$work\logs"
$env:PAPERLESS_REDIS = "redis://127.0.0.1:$BrokerPort"
$env:PAPERLESS_SECRET_KEY = 'office-integration-secret-key-not-for-production'
$env:PAPERLESS_ADMIN_USER = 'admin'; $env:PAPERLESS_ADMIN_PASSWORD = 'office-test-pw'
$env:PAPERLESS_PORT = "$WebPort"; $env:PAPERLESS_BIND_ADDR = '127.0.0.1'
$env:PAPERLESS_TASK_WORKERS = '2'
$env:PAPERLESS_TIKA_ENABLED = 'true'
$env:PAPERLESS_WIN_JAVA = $Java
$env:PAPERLESS_WIN_APP_DIR = $root
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = "$root\src"
Set-Location "$root\src"
if ($StaticFrom -and (Test-Path "$StaticFrom\.collected-version")) { Copy-Item $StaticFrom "$work\static" -Recurse }

$base = "http://localhost:$WebPort"
$auth = @{ Authorization = 'Basic ' + [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes('admin:office-test-pw')) }
$failures = [System.Collections.Generic.List[string]]::new()
function Assert-That([bool]$Condition, [string]$Message) {
    if ($Condition) { Write-Host "  PASS  $Message" -ForegroundColor Green }
    else { Write-Host "  FAIL  $Message" -ForegroundColor Red; $script:failures.Add($Message) }
}
function Wait-Until([scriptblock]$Condition, [int]$Seconds) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $Seconds) { if (& $Condition) { return $sw.Elapsed.TotalSeconds }; Start-Sleep -Seconds 2 }
    return $null
}
function Get-Json([string]$Path) { Invoke-RestMethod "$base$Path" -Headers $auth }
function Test-WebUp { try { (Invoke-WebRequest "$base/api/" -SkipHttpErrorCheck -TimeoutSec 3).StatusCode -in 200, 401, 403 } catch { $false } }
function Get-DocumentCount { (Get-Json '/api/documents/?page_size=1').count }
$script:stack = $null
function Start-Stack([hashtable]$Extra = @{}, [switch]$Init) {
    foreach ($k in $Extra.Keys) { Set-Item "Env:$k" $Extra[$k] }
    $arguments = @('-m', 'paperless_win', 'run') + $(if ($Init) { '--init' } else { @() })
    $script:stack = Start-Process $Python -ArgumentList $arguments -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput "$work\stack.out.log" -RedirectStandardError "$work\stack.err.log"
    $up = Wait-Until { Test-WebUp } 600
    if ($null -eq $up) { throw 'the web interface did not come up in 10 minutes' }
}
function Stop-Stack {
    & $Python -m paperless_win stop --timeout 40 | Out-Null
    if ($script:stack -and -not $script:stack.WaitForExit(30000)) { $script:stack.Kill($true) }
}
function Show-Logs {
    foreach ($f in 'supervisor.log', 'paperless.log') {
        $p = Join-Path $work "logs\$f"
        if (Test-Path $p) { "::group::$f"; Get-Content $p -Tail 60; '::endgroup::' }
    }
    foreach ($f in 'stack.err.log', 'stack.out.log') { if (Test-Path "$work\$f") { "::group::$f"; Get-Content "$work\$f" -Tail 40; '::endgroup::' } }
}

try {
    # --- 1. check ------------------------------------------------------------------------------------------------
    Write-Host '1. paperless-ctl check'
    $checkText = (& $Python -m paperless_win check 2>&1 | Out-String)
    Assert-That ($checkText -match 'Office documents and e-mail: Tika, LibreOffice and a browser are available') 'check finds Tika, LibreOffice and a browser'

    # --- 2. the five formats -----------------------------------------------------------------------------------------
    Write-Host '2. DOCX, ODT, XLSX, PPTX and an HTML e-mail'
    Start-Stack -Init
    $names = 'office-text.docx', 'office-text.odt', 'office-sheet.xlsx', 'office-slides.pptx', 'office-mail.eml'
    foreach ($n in $names) { Copy-Item "$fixtures\$n" "$env:PAPERLESS_CONSUMPTION_DIR\$n" }
    $t = Wait-Until { (Get-DocumentCount) -ge $names.Count } 300
    Assert-That ($null -ne $t) "all $($names.Count) files became documents ($([math]::Round($t, 0)) s)"
    $docs = (Get-Json '/api/documents/?page_size=50&fields=id,original_file_name,archived_file_name,content').results
    foreach ($n in $names) {
        $d = $docs | Where-Object { $_.original_file_name -eq $n }
        Assert-That ($null -ne $d -and $d.archived_file_name) "$n has an archive PDF"
        Assert-That ($null -ne $d -and $d.content -match 'kingfisher') "${n}: its text is searchable (contains the known word)"
    }

    # --- 3. 20 at once -----------------------------------------------------------------------------------------------
    Write-Host "3. $Batch conversions at the same moment"
    $before = Get-DocumentCount
    $files = @()
    for ($i = 0; $i -lt $Batch; $i++) {
        $target = "$work\batch-$('{0:D2}' -f $i).docx"
        & $Python -c "import sys, zipfile; src, out, tag = sys.argv[1:4]; zin = zipfile.ZipFile(src); zout = zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED); [zout.writestr(i, zin.read(i.filename).replace(b'kingfisher', ('batch' + tag).encode()) if i.filename == 'word/document.xml' else zin.read(i.filename)) for i in zin.infolist()]; zout.close()" "$fixtures\office-text.docx" $target ('{0:D2}' -f $i)
        $files += $target
    }
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $files | ForEach-Object -ThrottleLimit $Batch -Parallel {
        Invoke-RestMethod "$using:base/api/documents/post_document/" -Method Post -Headers $using:auth -Form @{ document = Get-Item $_ } | Out-Null
    }
    $t = Wait-Until { (Get-DocumentCount) -ge ($before + $Batch) } 900
    Assert-That ($null -ne $t) "all $Batch uploads became documents ($([math]::Round($sw.Elapsed.TotalSeconds, 0)) s in all)"
    $tasks = (Get-Json '/api/tasks/?page_size=200')
    $tasks = if ($tasks.results) { $tasks.results } else { $tasks }
    $failed = @($tasks | Where-Object { $_.status -eq 'failure' })
    Assert-That ($failed.Count -eq 0) "no task failed ($($failed.Count) did)"
    Start-Sleep -Seconds 15
    $left = @(Get-Process soffice, soffice.bin -ErrorAction SilentlyContinue)
    Assert-That ($left.Count -eq 0) "no soffice process is left behind ($($left.Count) found)"
    Stop-Stack

    # --- 4. LibreOffice missing -----------------------------------------------------------------------------------
    Write-Host '4. a missing LibreOffice is explained'
    Start-Stack @{ PAPERLESS_WIN_SOFFICE = "$work\no-such-folder\soffice.exe" }
    Copy-Item "$work\batch-00.docx" "$work\missing.docx"
    & $Python -c "import zipfile, sys; zin = zipfile.ZipFile(sys.argv[1]); zout = zipfile.ZipFile(sys.argv[2], 'w'); [zout.writestr(i, zin.read(i.filename).replace(b'batch00', b'nolibreoffice') if i.filename == 'word/document.xml' else zin.read(i.filename)) for i in zin.infolist()]; zout.close()" "$work\batch-00.docx" "$env:PAPERLESS_CONSUMPTION_DIR\missing.docx"
    $message = $null
    $t = Wait-Until {
        $r = Get-Json '/api/tasks/?page_size=10'
        $r = if ($r.results) { $r.results } else { $r }
        $f = $r | Where-Object { $_.status -eq 'failure' -and ($_ | ConvertTo-Json -Depth 5) -match 'missing.docx' } | Select-Object -First 1
        if ($f) { $script:message = ($f | ConvertTo-Json -Depth 5) }
        [bool]$f
    } 240
    Assert-That ($null -ne $t) 'the document fails'
    Assert-That ($message -match 'LibreOffice was not found') 'the task says LibreOffice was not found'
    Assert-That ($message -match 'libreoffice.org/download') 'the task says where to get it'
    Assert-That ($message -match 'PAPERLESS_WIN_SOFFICE') 'the task names the setting for a non-standard place'
    Stop-Stack
}
catch {
    Write-Host "ERROR: $_" -ForegroundColor Red
    $failures.Add("unexpected error: $_")
}
finally {
    if ($failures.Count -gt 0) { Show-Logs }
    try { Stop-Stack } catch { Write-Verbose $_ }
    if (-not $Keep) { Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue } else { Write-Host "Kept $work" }
}

if ($failures.Count -gt 0) {
    Write-Host "Office integration test FAILED: $($failures.Count) check(s)" -ForegroundColor Red
    exit 1
}
Write-Host 'Office integration test passed.' -ForegroundColor Green
exit 0
