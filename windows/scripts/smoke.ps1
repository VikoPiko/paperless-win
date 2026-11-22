#Requires -Version 7
<#
.SYNOPSIS
  End-to-end smoke test against a running paperless-win (or any paperless-ngx) instance.

.DESCRIPTION
  Assumes the services are already running and these variables are set:
    PAPERLESS_URL   e.g. http://localhost:8000
    PAPERLESS_USER  user with permission to add/delete documents
    PAPERLESS_PASS  that user's password

  Uploads windows/fixtures/smoke.pdf through the REST API, waits (max 5 min) for the
  consume task, then asserts: the document exists, its OCR content contains the known
  word, the thumbnail returns 200, the original downloads, and full-text search finds it.
  The uploaded document is deleted afterwards unless -Keep is given.
  Exit code 0 = all assertions passed, 1 = a failure, 2 = bad setup.
#>
[CmdletBinding()]
param(
    [string]$Fixture = (Join-Path $PSScriptRoot '..\fixtures\smoke.pdf'),
    [string]$KnownWord = 'zebrafish',
    [int]$TimeoutSeconds = 300,
    [switch]$Keep
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

foreach ($name in 'PAPERLESS_URL', 'PAPERLESS_USER', 'PAPERLESS_PASS') {
    if (-not (Get-Item "Env:$name" -ErrorAction SilentlyContinue)) { Write-Error "$name is not set"; exit 2 }
}
if (-not (Test-Path $Fixture)) { Write-Error "fixture not found: $Fixture"; exit 2 }

$base = $env:PAPERLESS_URL.TrimEnd('/')
$basic = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("$($env:PAPERLESS_USER):$($env:PAPERLESS_PASS)"))
$headers = @{ Authorization = "Basic $basic"; Accept = 'application/json; version=9' }

$failures = [System.Collections.Generic.List[string]]::new()
function Assert-That([bool]$Condition, [string]$Message) {
    if ($Condition) { Write-Host "  PASS  $Message" -ForegroundColor Green }
    else { Write-Host "  FAIL  $Message" -ForegroundColor Red; $script:failures.Add($Message) }
}

# 1. upload ------------------------------------------------------------------------------
$title = "winport-smoke-$([guid]::NewGuid().ToString('N').Substring(0, 8))"
Write-Host "Uploading $Fixture as '$title' to $base"
$taskId = Invoke-RestMethod "$base/api/documents/post_document/" -Method Post -Headers $headers `
    -Form @{ document = (Get-Item $Fixture); title = $title }
$taskId = "$taskId".Trim('"')
Write-Host "  task $taskId"

# 2. poll the task -------------------------------------------------------------------------
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$task = $null
do {
    Start-Sleep -Seconds 2
    $task = @(Invoke-RestMethod "$base/api/tasks/?task_id=$taskId" -Headers $headers) | Select-Object -First 1
} while ($task -and $task.status -notin 'SUCCESS', 'FAILURE', 'REVOKED' -and (Get-Date) -lt $deadline)

Assert-That ($null -ne $task -and $task.status -eq 'SUCCESS') "consume task finished with SUCCESS (status: $($task.status); result: $($task.result))"
if (-not $task -or $task.status -ne 'SUCCESS' -or -not $task.related_document) {
    Write-Host "Smoke test FAILED: $($failures.Count) assertion(s)" -ForegroundColor Red
    exit 1
}
$id = [int]$task.related_document

try {
    # 3. document + content ------------------------------------------------------------------
    $doc = Invoke-RestMethod "$base/api/documents/$id/" -Headers $headers
    Assert-That ($doc.id -eq $id) "document $id exists"
    Assert-That ("$($doc.content)" -match [regex]::Escape($KnownWord)) "OCR content contains '$KnownWord'"

    # 4. thumbnail and original ----------------------------------------------------------------
    $thumb = Invoke-WebRequest "$base/api/documents/$id/thumb/" -Headers $headers -SkipHttpErrorCheck
    Assert-That ($thumb.StatusCode -eq 200 -and $thumb.Content.Length -gt 0) "thumbnail returns 200 ($($thumb.StatusCode))"
    $orig = Invoke-WebRequest "$base/api/documents/$id/download/?original=true" -Headers $headers -SkipHttpErrorCheck
    Assert-That ($orig.StatusCode -eq 200 -and $orig.Content.Length -gt 0) "original downloads ($($orig.StatusCode))"

    # 5. full-text search (the index is updated shortly after the task completes) -----------------
    $found = $false
    $searchDeadline = (Get-Date).AddSeconds(60)
    do {
        $res = Invoke-RestMethod "$base/api/documents/?query=$([uri]::EscapeDataString($KnownWord))" -Headers $headers
        $found = @($res.results | Where-Object { $_.id -eq $id }).Count -gt 0
        if (-not $found) { Start-Sleep -Seconds 2 }
    } while (-not $found -and (Get-Date) -lt $searchDeadline)
    Assert-That $found "search for '$KnownWord' finds document $id"
}
finally {
    if (-not $Keep) {
        Invoke-RestMethod "$base/api/documents/$id/" -Method Delete -Headers $headers | Out-Null
        Write-Host "  (deleted document $id)"
    }
}

if ($failures.Count -gt 0) {
    Write-Host "Smoke test FAILED: $($failures.Count) assertion(s)" -ForegroundColor Red
    exit 1
}
Write-Host 'Smoke test passed.' -ForegroundColor Green
exit 0
