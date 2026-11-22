#Requires -Version 7
<#
.SYNOPSIS
  Integration tests for `paperless-ctl` and the supervisor, against a real stack.

.DESCRIPTION
  Uses its own data folder (-WorkDir, default %TEMP%\paperless-win-integration), so it never
  touches real data. The first run is slow (init collects the static files, several minutes);
  later runs reuse them. Needs the dev tools from bootstrap-dev.ps1 (.tools\) and the .venv.

  Scenarios:
    1. init, run, wait for the web UI, smoke.ps1 passes
    2. kill -9 a worker: the supervisor starts a new one within 5 s
    3. recycling: after a task the worker is replaced (and a task still works afterwards)
    4. a task that hangs past the time limit: the worker and ITS CHILDREN are killed, the
       task shows as FAILURE, the worker comes back
    5. Ctrl-C: every process exits within 15 s, nothing is left behind
    6. `paperless-ctl stop` while a task is running: same, and the interrupted task is marked
       failed on the next start

  Exit code 0 = all passed, 1 = a check failed, 2 = bad setup.
#>
[CmdletBinding()]
param(
    [string]$WorkDir = (Join-Path $env:TEMP 'paperless-win-integration'),
    [int]$Port = 8011,
    [int]$BrokerPort = 6391,
    [int]$TimeLimit = 40,
    [switch]$SkipInit
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { Write-Error "python not found: $python (run windows\scripts\bootstrap-dev.ps1)"; exit 2 }

# --- environment (clean: no inherited PAPERLESS_* settings) -------------------------------------
Get-ChildItem Env: | Where-Object { $_.Name -like 'PAPERLESS_*' } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
New-Item -ItemType Directory -Force $WorkDir | Out-Null
$hangFlag = Join-Path $WorkDir 'hang.flag'
Remove-Item $hangFlag -ErrorAction SilentlyContinue
$hangScript = Join-Path $WorkDir 'pre-consume.ps1'
@"
# test pre-consume script: while the flag file exists, hang (with a child process) past the time limit.
# -NoNewWindow matters: a process started through ShellExecute (the Start-Process default) is not
# inside the job object and survives the watchdog.
if (Test-Path '$hangFlag') {
    Start-Process -FilePath ping -ArgumentList '-n','600','127.0.0.1' -NoNewWindow
    Start-Sleep -Seconds 600
}
"@ | Set-Content $hangScript

$env:PAPERLESS_DATA_DIR = "$WorkDir\data"; $env:PAPERLESS_MEDIA_ROOT = "$WorkDir\media"
$env:PAPERLESS_CONSUMPTION_DIR = "$WorkDir\consume"; $env:PAPERLESS_SCRATCH_DIR = "$WorkDir\scratch"
$env:PAPERLESS_STATICDIR = "$WorkDir\static"; $env:PAPERLESS_LOGGING_DIR = "$WorkDir\logs"
$env:PAPERLESS_REDIS = "redis://127.0.0.1:$BrokerPort"
$env:PAPERLESS_SECRET_KEY = 'integration-test-secret'
$env:PAPERLESS_ADMIN_USER = 'admin'; $env:PAPERLESS_ADMIN_PASSWORD = 'integration-pw'
$env:PAPERLESS_BIND_ADDR = '127.0.0.1'; $env:PAPERLESS_PORT = "$Port"
$env:PAPERLESS_URL = "http://localhost:$Port"
$env:PAPERLESS_TASK_WORKERS = '2'
$env:PAPERLESS_WORKER_TIMEOUT = "$TimeLimit"
$env:PAPERLESS_WIN_WATCHDOG_GRACE = '5'
$env:PAPERLESS_PRE_CONSUME_SCRIPT = $hangScript
$env:PAPERLESS_WIN_APP_DIR = $root
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = "$root\src"
$runDir = "$WorkDir\logs\run"
$base = "http://localhost:$Port"
$headers = @{ Authorization = 'Basic ' + [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes('admin:integration-pw')); Accept = 'application/json; version=9' }
Set-Location "$root\src"

$failures = [System.Collections.Generic.List[string]]::new()
function Assert-That([bool]$Condition, [string]$Message) {
    if ($Condition) { Write-Host "  PASS  $Message" -ForegroundColor Green }
    else { Write-Host "  FAIL  $Message" -ForegroundColor Red; $script:failures.Add($Message) }
}
function Get-State { try { Get-Content "$runDir\state.json" -Raw | ConvertFrom-Json } catch { $null } }
function Get-ChildState([string]$Name) { (Get-State).children | Where-Object name -eq $Name }
function Wait-Until([scriptblock]$Condition, [int]$Seconds, [int]$PollMs = 250) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $Seconds) { if (& $Condition) { return $sw.Elapsed.TotalSeconds }; Start-Sleep -Milliseconds $PollMs }
    return $null
}
function Start-Stack {
    # No output redirection: the supervisor then gets a console of its own, which the Ctrl-C test
    # needs. Its output is in <logs>\supervisor.log anyway.
    $p = Start-Process $python -ArgumentList '-m', 'paperless_win', 'run' -WorkingDirectory "$root\src" -WindowStyle Hidden -PassThru
    $up = Wait-Until { try { (Invoke-WebRequest "$base/api/" -SkipHttpErrorCheck -TimeoutSec 3).StatusCode -in 200, 401, 403 } catch { $false } } 90
    if ($null -eq $up) { Write-Host (Get-Content "$runDir\..\supervisor.log" -Tail 15 | Out-String); throw 'the web UI did not come up' }
    Start-Sleep -Seconds 8   # workers need a few seconds longer than the web server
    return $p
}
function Get-AllPids { $s = Get-State; @($s.children.pid | Where-Object { $_ }) + $s.supervisor_pid }
function Test-Gone($ids) { @(Get-Process -Id $ids -ErrorAction SilentlyContinue).Count -eq 0 }
function Send-Upload {
    (Invoke-RestMethod "$base/api/documents/post_document/" -Method Post -Headers $headers -Form @{ document = (Get-Item "$root\windows\fixtures\smoke.pdf") }).Trim('"')
}
function Get-Task($id) { @(Invoke-RestMethod "$base/api/tasks/?task_id=$id" -Headers $headers) | Select-Object -First 1 }
function Remove-AllDocuments {
    foreach ($d in (Invoke-RestMethod "$base/api/documents/?fields=id&page_size=100" -Headers $headers).results) {
        Invoke-RestMethod "$base/api/documents/$($d.id)/" -Method Delete -Headers $headers | Out-Null
    }
}

# --- 1. init + run + smoke ----------------------------------------------------------------------
Write-Host '1. init, run, smoke test'
if (-not $SkipInit) {
    & $python -m paperless_win init
    Assert-That ($LASTEXITCODE -eq 0) 'paperless-ctl init succeeds on a clean data folder'
    & $python -m paperless_win init
    Assert-That ($LASTEXITCODE -eq 0) 'paperless-ctl init is idempotent (second run)'
}
$sup = Start-Stack
$names = (Get-State).children.name
Assert-That (($names -join ',') -eq 'garnet,web,beat,consumer,worker1,worker2') "children: $($names -join ', ')"
$env:PAPERLESS_USER = 'admin'; $env:PAPERLESS_PASS = 'integration-pw'
pwsh -NoProfile -File "$PSScriptRoot\smoke.ps1"
Assert-That ($LASTEXITCODE -eq 0) 'smoke.ps1 passes against the supervised stack'
& $python -m paperless_win status | Out-Host
Assert-That ($LASTEXITCODE -eq 0) 'paperless-ctl status reports the stack as running'

# --- 2. kill a worker -----------------------------------------------------------------------------
Write-Host '2. kill a worker'
$w = Get-ChildState 'worker1'
Stop-Process -Id $w.pid -Force
$t = Wait-Until { $n = Get-ChildState 'worker1'; $n.pid -and $n.pid -ne $w.pid -and $n.state -eq 'running' } 20
Assert-That ($null -ne $t -and $t -le 5) "worker1 restarted within 5 s (took $([math]::Round($t, 1)) s)"

# --- 3. recycling -----------------------------------------------------------------------------------
Write-Host '3. recycling after a task'
Start-Sleep -Seconds 8
$before = @((Get-State).children | Where-Object name -like 'worker*' | ForEach-Object { "$($_.name):$($_.pid)" })
$id = Send-Upload
$t = Wait-Until { (Get-Task $id).status -in 'SUCCESS', 'FAILURE' } 120
Assert-That ($null -ne $t -and (Get-Task $id).status -eq 'SUCCESS') 'a consume task succeeds'
Start-Sleep -Seconds 12
$after = @((Get-State).children | Where-Object name -like 'worker*' | ForEach-Object { "$($_.name):$($_.pid)" })
Assert-That (@($after | Where-Object { $before -notcontains $_ }).Count -ge 1) "a worker was replaced after its task (before: $($before -join ' '); after: $($after -join ' '))"
Remove-AllDocuments

# --- 4. hung task -----------------------------------------------------------------------------------
Write-Host "4. a task that hangs past the $TimeLimit s limit"
Start-Sleep -Seconds 8
'1' | Set-Content $hangFlag
$pingBefore = @(Get-Process ping -ErrorAction SilentlyContinue).Count
$id = Send-Upload
$t = Wait-Until { @(Get-Process ping -ErrorAction SilentlyContinue).Count -gt $pingBefore } 60
Assert-That ($null -ne $t) 'the hanging task is running (its child process exists)'
$t = Wait-Until { (Get-Task $id).status -eq 'FAILURE' } ($TimeLimit + 40)
Assert-That ($null -ne $t) "the task shows as FAILURE ($((Get-Task $id).result))"
Assert-That ($t -le ($TimeLimit + 25)) "it was stopped about the time limit (after $([math]::Round($t + 8, 0)) s)"
Remove-Item $hangFlag
$t = Wait-Until { @(Get-Process ping -ErrorAction SilentlyContinue).Count -le $pingBefore } 10
Assert-That ($null -ne $t) "the hung task's child processes were killed too"
$t = Wait-Until { (Get-State).children | Where-Object { $_.name -like 'worker*' -and $_.state -ne 'running' } | Measure-Object | ForEach-Object { $_.Count -eq 0 } } 30
Assert-That ($null -ne $t) 'both workers are running again'
Start-Sleep -Seconds 8
$id = Send-Upload
$t = Wait-Until { (Get-Task $id).status -in 'SUCCESS', 'FAILURE' } 120
Assert-That ((Get-Task $id).status -eq 'SUCCESS') 'a normal task still works afterwards'
Remove-AllDocuments

# --- 5. Ctrl-C ------------------------------------------------------------------------------------------
Write-Host '5. Ctrl-C'
$ids = Get-AllPids
$sw = [Diagnostics.Stopwatch]::StartNew()
& $python "$PSScriptRoot\send_ctrl_c.py" $sup.Id
Assert-That ($LASTEXITCODE -eq 0) 'Ctrl-C was delivered to the supervisor console'
$exited = $null -ne (Wait-Until { $sup.HasExited } 20)
Assert-That $exited "the supervisor exited after Ctrl-C ($([math]::Round($sw.Elapsed.TotalSeconds, 1)) s)"
Assert-That ($sw.Elapsed.TotalSeconds -le 15) 'within 15 s'
Assert-That (Test-Gone $ids) "no process of the stack is left (checked $($ids.Count) pids)"
Assert-That (@(Get-Process ping -ErrorAction SilentlyContinue).Count -le $pingBefore) 'no stray child processes'

# --- 6. stop while a task runs ----------------------------------------------------------------------------
Write-Host '6. paperless-ctl stop during a running task'
$sup = Start-Stack
'1' | Set-Content $hangFlag
$id = Send-Upload
Start-Sleep -Seconds 10
$ids = Get-AllPids
$sw = [Diagnostics.Stopwatch]::StartNew()
& $python -m paperless_win stop | Out-Host
Assert-That ($sw.Elapsed.TotalSeconds -le 15) "stop finished in $([math]::Round($sw.Elapsed.TotalSeconds, 1)) s"
Assert-That (Test-Gone $ids) 'no process of the stack is left'
Remove-Item $hangFlag
$sup = Start-Stack
$t = Wait-Until { (Get-Task $id).status -eq 'FAILURE' } 30
Assert-That ($null -ne $t) "the interrupted task was marked as failed at the next start ($((Get-Task $id).result))"
Remove-AllDocuments
& $python -m paperless_win stop | Out-Host

if ($failures.Count -gt 0) {
    Write-Host "Integration tests FAILED: $($failures.Count) check(s)" -ForegroundColor Red
    exit 1
}
Write-Host 'Integration tests passed.' -ForegroundColor Green
exit 0
