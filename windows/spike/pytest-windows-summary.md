# Backend tests on native Windows (P1 baseline)

Upstream v3.5.1, Python 3.13.13, Windows 11, `pytest -p no:randomly -n auto` (default addopts otherwise, coverage off). Run: 300 s.
Result line: **147 failed, 50 errors, 3948 passed, 13 skipped** (JUnit counts below; reruns are folded in).
Generated with `windows/scripts/summarize_failures.py`; root causes are in `windows/tasks/01-spike.md` (Findings).

## Summary of junit-windows.xml: 4187 test cases

error=50, failed=145, passed=3979, skipped=13

### Failures by exception type

| Count | Name                |
| ----: | ------------------- |
|    54 | `FileNotFoundError` |
|    50 | `AssertionError`    |
|    33 | `ParseError`        |
|    24 | `AttributeError`    |
|    13 | `PermissionError`   |
|    10 | `ConsumerError`     |
|     8 | `FileExistsError`   |
|     2 | `OSError`           |
|     1 | `ValueError`        |

### Failures by module

| Count | Name                                                     |
| ----: | -------------------------------------------------------- |
|    50 | `src.paperless_mail.tests.test_preprocessor`             |
|    34 | `src.paperless.tests.parsers.test_tesseract_parser`      |
|    24 | `src.documents.tests.test_api_status`                    |
|    13 | `src.documents.tests.test_file_handling`                 |
|     8 | `src.documents.tests.test_api_bulk_download`             |
|     7 | `src.documents.tests.test_management_exporter`           |
|     7 | `src.documents.tests.test_barcodes`                      |
|     6 | `src.documents.tests.test_filepath_nfc`                  |
|     5 | `src.documents.tests.test_api_objects`                   |
|     5 | `src.paperless.tests.test_checks`                        |
|     4 | `src.documents.tests.test_consumer`                      |
|     4 | `src.paperless.tests.parsers.test_text_parser`           |
|     4 | `src.documents.tests.test_tasks`                         |
|     3 | `src.documents.tests.test_workflows`                     |
|     3 | `src.documents.tests.test_management_importer`           |
|     3 | `src.documents.tests.test_sanity_check`                  |
|     3 | `src.documents.tests.test_management`                    |
|     3 | `src.documents.tests.test_share_link_bundles`            |
|     2 | `src.paperless.tests.parsers.test_mail_parser`           |
|     1 | `src.documents.tests.test_api_app_config`                |
|     1 | `src.documents.tests.test_api_documents`                 |
|     1 | `src.documents.tests.test_classifier`                    |
|     1 | `src.documents.tests.test_task_signals`                  |
|     1 | `src.documents.tests.test_parsers`                       |
|     1 | `src.paperless_ai.tests.test_vector_store`               |
|     1 | `src.documents.tests.test_permission_filtering_security` |

### Top exception per failing module

- 50 src.paperless_mail.tests.test_preprocessor (FileNotFoundError x50)
- 34 src.paperless.tests.parsers.test_tesseract_parser (ParseError x33)
- 24 src.documents.tests.test_api_status (AttributeError x24)
- 13 src.documents.tests.test_file_handling (AssertionError x12)
-     8  src.documents.tests.test_api_bulk_download  (PermissionError x8)
-     7  src.documents.tests.test_management_exporter  (FileExistsError x6)
-     7  src.documents.tests.test_barcodes  (ConsumerError x7)
-     6  src.documents.tests.test_filepath_nfc  (AssertionError x6)
-     5  src.documents.tests.test_api_objects  (AssertionError x5)
-     5  src.paperless.tests.test_checks  (AssertionError x5)
-     4  src.documents.tests.test_consumer  (FileNotFoundError x3)
-     4  src.paperless.tests.parsers.test_text_parser  (AssertionError x2)
-     4  src.documents.tests.test_tasks  (AssertionError x3)
-     3  src.documents.tests.test_workflows  (ConsumerError x3)
-     3  src.documents.tests.test_management_importer  (AssertionError x3)
-     3  src.documents.tests.test_sanity_check  (AssertionError x3)
-     3  src.documents.tests.test_management  (AssertionError x3)
-     3  src.documents.tests.test_share_link_bundles  (PermissionError x3)
-     2  src.paperless.tests.parsers.test_mail_parser  (AssertionError x2)
-     1  src.documents.tests.test_api_app_config  (AssertionError x1)
-     1  src.documents.tests.test_api_documents  (AssertionError x1)
-     1  src.documents.tests.test_classifier  (FileExistsError x1)
-     1  src.documents.tests.test_task_signals  (AssertionError x1)
-     1  src.documents.tests.test_parsers  (AssertionError x1)
-     1  src.paperless_ai.tests.test_vector_store  (PermissionError x1)
-     1  src.documents.tests.test_permission_filtering_security  (PermissionError x1)
