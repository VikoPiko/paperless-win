#Requires -Version 7
<#
.SYNOPSIS
  Long soak: consume files in a loop for hours while sampling the memory of every supervised
  process, then report the memory trend per process and any stuck tasks.

.DESCRIPTION
  Assumes the stack is running under `paperless-ctl run` (it reads the process list from
  <logs>\run\state.json) and PAPERLESS_URL / PAPERLESS_USER / PAPERLESS_PASS are set, like
  soak-consume.ps1, which this script calls repeatedly.

  Memory is the sum of private bytes of the process and all its descendants (Granian's worker
  process counts towards "web"), sampled every -SampleSeconds. For each name a straight line is
  fitted to the samples after a 30-minute warm-up; a slope above -MaxGrowthMBPerHour is a
  failure. Workers are recycled after a task, so for them the useful number is the peak.

  Writes <WorkDir>\soak-long-samples.csv. Exit code 0 = passed, 1 = failed, 2 = bad setup.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$ConsumeDir,
    [Parameter(Mandatory)] [string]$RunDir,        # <PAPERLESS_LOGGING_DIR>\run
    [double]$Hours = 4,
    [int]$FilesPerRun = 60,
    [int]$SampleSeconds = 60,
    [double]$WarmupMinutes = 30,
    [double]$MaxGrowthMBPerHour = 25,
    [string]$WorkDir = (Join-Path $env:TEMP 'paperless-soak-long')
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
foreach ($name in 'PAPERLESS_URL', 'PAPERLESS_USER', 'PAPERLESS_PASS') {
    if (-not (Get-Item "Env:$name" -ErrorAction SilentlyContinue)) { Write-Error "$name is not set"; exit 2 }
}
if (-not (Test-Path "$RunDir\state.json")) { Write-Error "no state.json in $RunDir: is the stack running?"; exit 2 }
New-Item -ItemType Directory -Force $WorkDir | Out-Null
$csv = Join-Path $WorkDir 'soak-long-samples.csv'
'minutes,name,pid,private_mb,processes' | Set-Content $csv
$base = $env:PAPERLESS_URL.TrimEnd('/')
$basic = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("$($env:PAPERLESS_USER):$($env:PAPERLESS_PASS)"))
$headers = @{ Authorization = "Basic $basic"; Accept = 'application/json; version=9' }

function Get-Tree([int]$RootPid, $All) {
    $ids = [System.Collections.Generic.HashSet[int]]::new(); [void]$ids.Add($RootPid)
    do { $added = $false
        foreach ($p in $All) { if ($ids.Contains([int]$p.ParentProcessId) -and $ids.Add([int]$p.ProcessId)) { $added = $true } }
    } while ($added)
    $ids
}
function Add-Samples([double]$Minutes) {
    $state = Get-Content "$RunDir\state.json" -Raw | ConvertFrom-Json
    $all = Get-CimInstance Win32_Process | Select-Object ProcessId, ParentProcessId
    $entries = @($state.children | Where-Object { $_.pid } | ForEach-Object { @{ name = $_.name; pid = [int]$_.pid } }) + @{ name = 'supervisor'; pid = [int]$state.supervisor_pid }
    foreach ($e in $entries) {
        $tree = Get-Tree $e.pid $all
        $procs = @(Get-Process -Id @($tree) -ErrorAction SilentlyContinue)
        if ($procs.Count -eq 0) { continue }
        $mb = ($procs | Measure-Object PrivateMemorySize64 -Sum).Sum / 1MB
        '{0:N1},{1},{2},{3:N1},{4}' -f $Minutes, $e.name, $e.pid, $mb, $procs.Count | Add-Content $csv
    }
}

$started = Get-Date
$deadline = $started.AddHours($Hours)
$run = 0; $failedRuns = 0
Write-Host "Soaking for $Hours h: $FilesPerRun files per run, sampling every $SampleSeconds s"
while ((Get-Date) -lt $deadline) {
    $run++
    $job = Start-Process pwsh -ArgumentList '-NoProfile', '-File', "$PSScriptRoot\soak-consume.ps1", '-ConsumeDir', $ConsumeDir, '-Count', $FilesPerRun, '-SlowWriters', 4, '-BurstSize', 15, '-TimeoutMinutes', 30 `
        -PassThru -WindowStyle Hidden -RedirectStandardOutput "$WorkDir\run-$run.out.log" -RedirectStandardError "$WorkDir\run-$run.err.log"
    while (-not $job.HasExited) {
        Add-Samples (((Get-Date) - $started).TotalMinutes)
        Start-Sleep -Seconds $SampleSeconds
    }
    if ($job.ExitCode -ne 0) { $failedRuns++; Write-Host "  run $run FAILED (see $WorkDir\run-$run.out.log)" -ForegroundColor Red }
    else { Write-Host ("  run {0} ok at {1:N0} min" -f $run, ((Get-Date) - $started).TotalMinutes) }
}
Add-Samples (((Get-Date) - $started).TotalMinutes)

# --- analysis ---------------------------------------------------------------------------------------------------
function Get-Slope($points) {   # least squares, points = @(@(x, y), ...); returns y per x
    $n = $points.Count; if ($n -lt 3) { return $null }
    $sx = ($points | ForEach-Object { $_[0] } | Measure-Object -Sum).Sum; $sy = ($points | ForEach-Object { $_[1] } | Measure-Object -Sum).Sum
    $sxy = ($points | ForEach-Object { $_[0] * $_[1] } | Measure-Object -Sum).Sum; $sxx = ($points | ForEach-Object { $_[0] * $_[0] } | Measure-Object -Sum).Sum
    $den = $n * $sxx - $sx * $sx; if ($den -eq 0) { return 0 }
    ($n * $sxy - $sx * $sy) / $den
}
$rows = Import-Csv $csv
$failures = [System.Collections.Generic.List[string]]::new()
Write-Host ''
Write-Host ('{0,-11} {1,8} {2,8} {3,8} {4,12}' -f 'process', 'first MB', 'last MB', 'peak MB', 'MB per hour')
foreach ($group in ($rows | Group-Object name)) {
    $mb = @($group.Group | ForEach-Object { [double]$_.private_mb })
    $late = @($group.Group | Where-Object { [double]$_.minutes -ge $WarmupMinutes } | ForEach-Object { , @([double]$_.minutes / 60, [double]$_.private_mb) })
    $slope = Get-Slope $late
    $slopeText = if ($null -eq $slope) { 'n/a' } else { '{0:N1}' -f $slope }
    Write-Host ('{0,-11} {1,8:N0} {2,8:N0} {3,8:N0} {4,12}' -f $group.Name, $mb[0], $mb[-1], ($mb | Measure-Object -Maximum).Maximum, $slopeText)
    $recycled = $group.Name -like 'worker*'
    if (-not $recycled -and $null -ne $slope -and $slope -gt $MaxGrowthMBPerHour) { $failures.Add("$($group.Name) grows $slopeText MB/hour") }
}

# --- stuck tasks -----------------------------------------------------------------------------------------------------
Start-Sleep -Seconds 20
$tasks = @(Invoke-RestMethod "$base/api/tasks/" -Headers $headers)
$stuck = @($tasks | Where-Object { $_.status -in 'STARTED', 'PENDING' })
if ($stuck.Count -gt 0) { $failures.Add("$($stuck.Count) task(s) still pending/started: $(($stuck | Select-Object -First 3 | ForEach-Object { $_.task_id }) -join ', ')") }
if ($failedRuns -gt 0) { $failures.Add("$failedRuns of $run soak run(s) failed") }

Write-Host ''
Write-Host "$run run(s), $($rows.Count) samples in $csv"
if ($failures.Count -gt 0) {
    $failures | ForEach-Object { Write-Host "  FAIL  $_" -ForegroundColor Red }
    exit 1
}
Write-Host 'Long soak passed: no memory growth trend, no stuck tasks, every file consumed once.' -ForegroundColor Green
exit 0
