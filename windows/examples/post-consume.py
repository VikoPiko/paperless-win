# ruff: noqa: INP001, T201
"""Example post-consume script for paperless-win (Python). Run with the service's own Python.

Configure with PAPERLESS_POST_CONSUME_SCRIPT=C:\\path\\to\\post-consume.py
A non-zero exit code marks the consume as failed.
"""

import os

print(f"A document with an id of {os.environ.get('DOCUMENT_ID')} was just consumed.")
for name in ("FILE_NAME", "SOURCE_PATH", "CORRESPONDENT", "TAGS"):
    print(f"* {name.replace('_', ' ').title()}: {os.environ.get('DOCUMENT_' + name)}")
