# Example post-consume script for paperless-win (PowerShell). Windows version of
# scripts/post-consumption-example.sh.
#
# Configure it with:   PAPERLESS_POST_CONSUME_SCRIPT=C:\path\to\post-consume.ps1
# paperless-win runs .ps1 files with:  pwsh -NoProfile -ExecutionPolicy Bypass -File <script>
# (falling back to Windows PowerShell 5.1). A non-zero exit code marks the consume as failed.
# The script is run once per consumed document, with these environment variables set.

$info = [ordered]@{
    'Document id'         = $env:DOCUMENT_ID
    'Generated file name' = $env:DOCUMENT_FILE_NAME
    'Document type'       = $env:DOCUMENT_TYPE
    'Archive path'        = $env:DOCUMENT_ARCHIVE_PATH
    'Source path'         = $env:DOCUMENT_SOURCE_PATH
    'Created'             = $env:DOCUMENT_CREATED
    'Added'               = $env:DOCUMENT_ADDED
    'Modified'            = $env:DOCUMENT_MODIFIED
    'Thumbnail path'      = $env:DOCUMENT_THUMBNAIL_PATH
    'Download URL'        = $env:DOCUMENT_DOWNLOAD_URL
    'Thumbnail URL'       = $env:DOCUMENT_THUMBNAIL_URL
    'Owner'               = $env:DOCUMENT_OWNER
    'Correspondent'       = $env:DOCUMENT_CORRESPONDENT
    'Tags'                = $env:DOCUMENT_TAGS
}

Write-Output ''
Write-Output "A document with an id of $($env:DOCUMENT_ID) was just consumed. Additional information:"
Write-Output ''
foreach ($key in $info.Keys) { Write-Output ("* {0}: {1}" -f $key, $info[$key]) }
Write-Output ''

# Example: append a line to a log file next to the data directory
# Add-Content -Path "$env:PAPERLESS_DATA_DIR\consumed.log" -Value "$(Get-Date -Format o) $($env:DOCUMENT_ID) $($env:DOCUMENT_FILE_NAME)"
