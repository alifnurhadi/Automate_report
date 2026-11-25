"""Single source of truth for where Jira snapshot output lives."""

from pathlib import Path

# utils/ -> python/ -> Script/ -> repo root
ROOT_DIR = Path(__file__).resolve().parents[3]

# Every script that saves/logs Jira snapshot data must use this folder.
SNAPSHOTS_DIR = ROOT_DIR / "jira_snapshots"

APPLY_ERROR_LOG = SNAPSHOTS_DIR / "apply_errors.log"
RESULT_LOG = SNAPSHOTS_DIR / "result.log"

PYTHON_DIR = Path(__file__).resolve().parents[1]
SECRET_PATH = PYTHON_DIR / "secret.json"
EDITABLE_FIELDS_PATH = PYTHON_DIR / "jira_editable_field.json"
SQL_DIR = ROOT_DIR / "Script" / "sql"
MSG_PATH = ROOT_DIR / "Docs" / "msg.json"
