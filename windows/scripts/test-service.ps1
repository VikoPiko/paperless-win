#Requires -Version 7
<#
.SYNOPSIS
  Integration test for the Windows service. MUST RUN IN AN ELEVATED (administrator) PowerShell.

.DESCRIPTION
  Uses its own data root (%ProgramData%\paperless-win-test, through PAPERLESS_WIN_DATA_ROOT) and
  its own ports, so a real installation is never touched. It refuses to run if the service
  "paperless-win" already exists.

    1. init, then `service install --start`
    2. the service is RUNNING, every stack process belongs to the service account, smoke.ps1 passes
    3. folder permissions: nobody but SYSTEM, Administrators and the service account can write to
       anything below the data root, except Users in the consume folder
    4. `service restart`, smoke.ps1 passes again
    5. `service stop`: STOPPED, no process of the stack is left
    6. failure messages: the broker port taken by another server, an invalid configuration
    7. `service uninstall`: the service is gone, data and configuration are kept, firewall rule removed

  After this script, reboot the machine once, start nothing, and check with
  `Get-Service paperless-win` / `paperless-ctl status` that the service came up by itself
  (that step cannot be automated here; see windows/tasks/09-windows-service.md).

  -Account  virtual (default for an installed layout) or system. A checkout under C:\Users cannot
            be read by a virtual account (the profile folders deny it), so there the default is
            system; run this script from an installed layout to test the virtual account for real.
  Exit code 0 = passed, 1 = a check failed, 2 = bad setup.
#>
[CmdletBinding()]
param(
    [ValidateSet('auto', 'virtual', 'system')] [string]$Account = 'auto',
    [string]$Python = '',
    [int]$WebPort = 8014,
    [int]$BrokerPort = 6394,
    [string]$StaticFrom = (Join-Path $env:TEMP 'paperless-win-integration\static'),
    [switch]$Keep
)
$ErrorActionPreference = 'Continue'   # setup problems exit with code 2 below; 'Stop' applies afterwards
$ProgressPreference = 'SilentlyContinue'
$root = (Resolve-Path "$PSScriptRoot\..\..").Path

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error 'This test installs a Windows service: run it in an elevated PowerShell (Run as administrator).'
    exit 2
}
if (-not $Python) { $Python = Join-Path $root '.venv\Scripts\python.exe' }
if (-not (Test-Path $Python)) { Write-Error "python not found: $Python"; exit 2 }
if (Get-Service paperless-win -ErrorAction SilentlyContinue) { Write-Error "The service 'paperless-win' already exists; this test will not touch it."; exit 2 }

if ($Account -eq 'auto') { $Account = if ($root.StartsWith($env:USERPROFILE, 'OrdinalIgnoreCase')) { 'system' } else { 'virtual' } }
$ErrorActionPreference = 'Stop'
Write-Host "Service account for this test: $Account" -ForegroundColor Cyan
if ($Account -eq 'virtual' -and $root.StartsWith($env:USERPROFILE, 'OrdinalIgnoreCase')) {
    Write-Warning 'This checkout is below your user profile; the virtual service account cannot read it, expect failures.'
}

# --- environment: own data root, own ports, own configuration -------------------------------------------------------------
Get-ChildItem Env: | Where-Object { $_.Name -like 'PAPERLESS_*' } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
$data = Join-Path $env:ProgramData 'paperless-win-test'
if ((Test-Path $data) -and (Get-ChildItem $data -Force | Select-Object -First 1)) { Write-Error "$data exists and is not empty; remove it first."; exit 2 }
New-Item -ItemType Directory -Force $data | Out-Null
$conf = Join-Path $data 'paperless.conf'
$adminPassword = 'service-test-pw'
@"
PAPERLESS_DATA_DIR=$data\data
PAPERLESS_MEDIA_ROOT=$data\media
PAPERLESS_CONSUMPTION_DIR=$data\consume
PAPERLESS_SCRATCH_DIR=$data\scratch
PAPERLESS_STATICDIR=$data\static
PAPERLESS_LOGGING_DIR=$data\logs
PAPERLESS_REDIS=redis://127.0.0.1:$BrokerPort
PAPERLESS_SECRET_KEY=service-test-secret-key
PAPERLESS_ADMIN_USER=admin
PAPERLESS_ADMIN_PASSWORD=$adminPassword
PAPERLESS_BIND_ADDR=127.0.0.1
PAPERLESS_PORT=$WebPort
PAPERLESS_TASK_WORKERS=2
"@ | Set-Content $conf -Encoding utf8
$env:PAPERLESS_WIN_DATA_ROOT = $data
$env:PAPERLESS_CONFIGURATION_PATH = $conf
$env:PAPERLESS_WIN_APP_DIR = $root
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = "$root\src"
Set-Location "$root\src"
if ((Test-Path $StaticFrom) -and (Test-Path "$StaticFrom\.collected-version")) {
    Write-Host "Reusing collected static files from $StaticFrom (saves several minutes)"
    Copy-Item $StaticFrom "$data\static" -Recurse
}
$base = "http://localhost:$WebPort"
$env:PAPERLESS_URL = $base; $env:PAPERLESS_USER = 'admin'; $env:PAPERLESS_PASS = $adminPassword

$failures = [System.Collections.Generic.List[string]]::new()
function Assert-That([bool]$Condition, [string]$Message) {
    if ($Condition) { Write-Host "  PASS  $Message" -ForegroundColor Green }
    else { Write-Host "  FAIL  $Message" -ForegroundColor Red; $script:failures.Add($Message) }
}
function Invoke-Ctl { & $Python -m paperless_win @args | Out-Host; return $LASTEXITCODE }
function Wait-Until([scriptblock]$Condition, [int]$Seconds) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $Seconds) { if (& $Condition) { return $sw.Elapsed.TotalSeconds }; Start-Sleep -Milliseconds 500 }
    return $null
}
function Test-WebUp { try { (Invoke-WebRequest "$base/api/" -SkipHttpErrorCheck -TimeoutSec 3).StatusCode -in 200, 401, 403 } catch { $false } }
function Get-StackProcesses {
    # everything started from this installation: the supervisor, its children and their children
    Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -and ($_.CommandLine -like "*$data*" -or $_.CommandLine -match 'paperless_win|GarnetServer|granian|celery') -and $_.ProcessId -ne $PID
    }
}
function Get-ServiceName { (Get-Service paperless-win -ErrorAction SilentlyContinue).Status }
function Show-Diagnostics {
    Write-Host '--- diagnostics ---' -ForegroundColor Yellow
    sc.exe queryex paperless-win | Out-Host
    foreach ($f in (Get-ChildItem "$data\logs" -Filter '*.log' -Recurse -ErrorAction SilentlyContinue | Sort-Object FullName)) {
        Write-Host "::group::$($f.FullName)"
        Get-Content $f.FullName -Tail 60 -ErrorAction SilentlyContinue | Out-Host
        Write-Host '::endgroup::'
    }
    Get-StackProcesses | Select-Object ProcessId, Name | Format-Table | Out-Host
}

try {
    # --- 1. init + install -------------------------------------------------------------------------------------------------
    Write-Host '1. init and install'
    Assert-That ((Invoke-Ctl init) -eq 0) 'paperless-ctl init succeeds'
    Assert-That ((Invoke-Ctl service install --account $Account --start) -eq 0) "paperless-ctl service install --account $Account --start succeeds"
    Assert-That ((Get-Service paperless-win).StartType -eq 'Automatic' -or (Get-CimInstance Win32_Service -Filter "Name='paperless-win'").StartMode -eq 'Auto') 'the service starts automatically at boot'

    # --- 2. running --------------------------------------------------------------------------------------------------------
    Write-Host '2. running as the right account, smoke test'
    $t = Wait-Until { Test-WebUp } 120
    Assert-That ($null -ne $t) "the web UI answers ($([math]::Round($t, 0)) s)"
    Start-Sleep -Seconds 10
    Assert-That ((Get-ServiceName) -eq 'Running') 'Get-Service says Running'
    $expectedOwner = if ($Account -eq 'system') { 'SYSTEM' } else { 'paperless-win' }
    $owners = @(Get-StackProcesses | ForEach-Object { (Invoke-CimMethod -InputObject $_ -MethodName GetOwner -ErrorAction SilentlyContinue).User } | Sort-Object -Unique)
    Assert-That ($owners.Count -gt 0 -and @($owners | Where-Object { $_ -ne $expectedOwner }).Count -eq 0) "every stack process runs as '$expectedOwner' (found: $($owners -join ', '))"
    pwsh -NoProfile -File "$PSScriptRoot\smoke.ps1"
    Assert-That ($LASTEXITCODE -eq 0) 'smoke.ps1 passes against the service'
    $serviceLogs = Get-ChildItem "$data\logs\service" -ErrorAction SilentlyContinue
    Assert-That (@($serviceLogs).Count -gt 0) "WinSW writes its own logs ($($serviceLogs.Name -join ', '))"

    # --- 3. permissions ----------------------------------------------------------------------------------------------------
    Write-Host '3. folder permissions'
    $svcSid = if ($Account -eq 'system') { 'S-1-5-18' } else { (& sc.exe showsid paperless-win | Select-String 'SERVICE SID').ToString().Split(':')[1].Trim() }
    # S-1-3-4 (OWNER RIGHTS) is whoever owns the file: Python gives the scratch folders it creates an owner-only
    # ACL (mode 0o700), and here the owner is the service account itself
    $allowedWriters = @('S-1-5-18', 'S-1-5-32-544', $svcSid, 'S-1-3-4')
    $writeRights = [Security.AccessControl.FileSystemRights]'WriteData, AppendData, CreateFiles, CreateDirectories, Delete, DeleteSubdirectoriesAndFiles, ChangePermissions, TakeOwnership'
    $bad = [System.Collections.Generic.List[string]]::new()
    $consume = Join-Path $data 'consume'
    foreach ($item in (@(Get-Item $data) + @(Get-ChildItem $data -Recurse -Force -ErrorAction SilentlyContinue | Where-Object { $_.FullName -notlike "$data\static\*" }))) {
        $acl = Get-Acl $item.FullName
        foreach ($ace in $acl.Access) {
            if ($ace.AccessControlType -ne 'Allow') { continue }
            if (($ace.FileSystemRights -band $writeRights) -eq 0) { continue }
            $sid = $ace.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
            if ($sid -in $allowedWriters) { continue }
            $inConsume = $item.FullName -eq $consume -or $item.FullName -like "$consume\*"
            if ($inConsume -and $sid -eq 'S-1-5-32-545') { continue }
            $bad.Add("$($item.FullName): $($ace.IdentityReference) $($ace.FileSystemRights)")
        }
        if ($bad.Count -gt 5) { break }
    }
    Assert-That ($bad.Count -eq 0) "no write access below the data root except SYSTEM, Administrators, the service account and Users in consume ($($bad | Select-Object -First 3 | Out-String))"
    $consumeAcl = (Get-Acl $consume).Access | Where-Object { $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value -eq 'S-1-5-32-545' }
    Assert-That (@($consumeAcl | Where-Object { $_.FileSystemRights -band [Security.AccessControl.FileSystemRights]::Modify }).Count -gt 0) 'Users can drop files into the consume folder (Modify)'
    $rootAcl = (Get-Acl $data).Access | Where-Object { $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value -eq 'S-1-5-32-545' }
    Assert-That (@($rootAcl).Count -eq 0) 'Users have no access at all to the data root (paperless.conf holds secrets)'

    # --- 4. restart ---------------------------------------------------------------------------------------------------------
    Write-Host '4. restart'
    Assert-That ((Invoke-Ctl service restart) -eq 0) 'paperless-ctl service restart succeeds'
    $t = Wait-Until { Test-WebUp } 120
    Assert-That ($null -ne $t) 'the web UI answers again'
    Start-Sleep -Seconds 10
    pwsh -NoProfile -File "$PSScriptRoot\smoke.ps1"
    Assert-That ($LASTEXITCODE -eq 0) 'smoke.ps1 passes after the restart'

    # --- 5. stop ------------------------------------------------------------------------------------------------------------
    Write-Host '5. stop'
    $sw = [Diagnostics.Stopwatch]::StartNew()
    Assert-That ((Invoke-Ctl service stop) -eq 0) 'paperless-ctl service stop succeeds'
    Assert-That ((Get-ServiceName) -eq 'Stopped') "the service is Stopped ($([math]::Round($sw.Elapsed.TotalSeconds, 1)) s)"
    Start-Sleep -Seconds 2
    $left = @(Get-StackProcesses)
    Assert-That ($left.Count -eq 0) "no process of the stack is left ($(($left | Select-Object -First 3 | ForEach-Object { "$($_.Name):$($_.ProcessId)" }) -join ', '))"

    # --- 6. failure messages -----------------------------------------------------------------------------------------------------
    Write-Host '6. failure messages'
    # 6a. another server already listens on the broker port
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $BrokerPort)
    $listener.Start()
    try {
        Remove-Item "$data\logs\service\*" -Include '*.err.log', '*.out.log' -ErrorAction SilentlyContinue
        Invoke-Ctl service start | Out-Null
        Start-Sleep -Seconds 15
        $text = (Get-Content "$data\logs\service\paperless-win-service.err.log", "$data\logs\service\paperless-win-service.out.log", "$data\logs\supervisor.log" -ErrorAction SilentlyContinue) -join "`n"
        Assert-That ($text -match 'garnet|broker|port') 'a taken broker port is reported in the logs (not just a crash)'
        Write-Host ($text -split "`n" | Select-String 'garnet|port' | Select-Object -Last 3 | Out-String)
    }
    finally {
        $listener.Stop()
        Invoke-Ctl service stop | Out-Null
        Start-Sleep -Seconds 3
    }
    # 6b. an invalid configuration value
    Add-Content $conf "`nPAPERLESS_TASK_WORKERS=not-a-number"
    Remove-Item "$data\logs\service\*" -Include '*.err.log', '*.out.log' -ErrorAction SilentlyContinue
    Invoke-Ctl service start | Out-Null
    Start-Sleep -Seconds 12
    $text = (Get-Content "$data\logs\service\paperless-win-service.err.log", "$data\logs\service\paperless-win-service.out.log" -ErrorAction SilentlyContinue) -join "`n"
    Assert-That ($text -match 'configuration is invalid|cannot load') 'an invalid configuration is reported in plain words'
    Invoke-Ctl service stop | Out-Null
    (Get-Content $conf | Where-Object { $_ -notmatch 'not-a-number' }) | Set-Content $conf -Encoding utf8

    # --- 7. uninstall ------------------------------------------------------------------------------------------------------------------
    Write-Host '7. uninstall'
    Assert-That ((Invoke-Ctl service firewall allow --port $WebPort) -eq 0) 'a firewall rule can be added'
    Assert-That ((Invoke-Ctl service uninstall) -eq 0) 'paperless-ctl service uninstall succeeds'
    Start-Sleep -Seconds 2
    Assert-That ($null -eq (Get-Service paperless-win -ErrorAction SilentlyContinue)) 'the service is gone'
    Assert-That ((Test-Path $conf) -and (Test-Path "$data\data") -and (Test-Path "$data\media")) 'configuration and data are kept'
    Assert-That (-not (netsh advfirewall firewall show rule name="paperless-win web interface" | Select-String 'Rule Name')) 'the firewall rule was removed'
}
catch {
    Write-Host "ERROR: $_" -ForegroundColor Red
    $failures.Add("unexpected error: $_")
}
finally {
    if ($failures.Count -gt 0) { Show-Diagnostics }
    if (Get-Service paperless-win -ErrorAction SilentlyContinue) {
        Write-Host 'Cleaning up: removing the test service' -ForegroundColor Yellow
        & $Python -m paperless_win service uninstall 2>&1 | Out-Host
    }
    if (-not $Keep) { Remove-Item $data -Recurse -Force -ErrorAction SilentlyContinue }
    else { Write-Host "Kept $data" }
}

if ($failures.Count -gt 0) {
    Write-Host "Service test FAILED: $($failures.Count) check(s)" -ForegroundColor Red
    exit 1
}
Write-Host 'Service test passed. Now reboot once and confirm the service starts by itself (see the task file).' -ForegroundColor Green
exit 0
