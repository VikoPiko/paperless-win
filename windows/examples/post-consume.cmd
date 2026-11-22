@echo off
rem Example post-consume script for paperless-win (batch file).
rem Configure with PAPERLESS_POST_CONSUME_SCRIPT=C:\path\to\post-consume.cmd
rem Run as: cmd /d /c <script>. A non-zero exit code marks the consume as failed.
echo A document with an id of %DOCUMENT_ID% was just consumed.
echo * Generated file name: %DOCUMENT_FILE_NAME%
echo * Source path: %DOCUMENT_SOURCE_PATH%
echo * Correspondent: %DOCUMENT_CORRESPONDENT%
echo * Tags: %DOCUMENT_TAGS%
exit /b 0
