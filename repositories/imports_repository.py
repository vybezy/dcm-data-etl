"""sql for import history: one row per import session with counts per outcome."""

from database import IMPORT_LOCK_ID
from repositories import common

# every file writes exactly one dicom_logger row, so counting rows = files processed
_SUMMARY = """
    SELECT s.logses_id AS id,
           s.logses_timestamp AS started_at,
           COUNT(l.log_id) AS processed,
           COUNT(*) FILTER (WHERE l.log_level = 'SUCCESS') AS inserted,
           COUNT(*) FILTER (WHERE l.log_level = 'DUPLICATE') AS duplicates,
           COUNT(*) FILTER (WHERE l.log_level = 'SKIP') AS skipped,
           COUNT(*) FILTER (WHERE l.log_level = 'DRYRUN') AS dry_run,
           COUNT(*) FILTER (WHERE l.log_level IN ('ERROR', 'CRITICAL')) AS errors
    FROM dicom_logger_session s
    LEFT JOIN dicom_logger l ON l.log_logses_id = s.logses_id
"""


def list_sessions(limit: int) -> list[dict]:
    return common.fetch_all(
        _SUMMARY + " GROUP BY s.logses_id ORDER BY s.logses_id DESC LIMIT %s", (limit,)
    )


_LOCK_HELD = """
    SELECT 1 FROM pg_locks
    WHERE locktype = 'advisory' AND granted
      AND database = (SELECT oid FROM pg_database WHERE datname = current_database())
      AND classid = 0 AND objid = %s AND objsubid = 1
"""


def import_lock_held() -> bool:
    return common.fetch_all(_LOCK_HELD, (IMPORT_LOCK_ID,)) != []
