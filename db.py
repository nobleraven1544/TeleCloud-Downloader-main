"""
db.py - SQLite-backed User Management for TeleCloud-Downloader.
"""

import re
import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

DB_PATH = "/app/user_configs/telecloud.db"

_local = threading.local()
_db_lock = threading.Lock()


def _get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return _local.conn


def _ensure_users_columns(conn: sqlite3.Connection) -> None:
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "username" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN username TEXT")
    if "display_name" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN display_name TEXT")
    # Monthly quota columns
    if "monthly_files_downloaded" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN monthly_files_downloaded INTEGER NOT NULL DEFAULT 0")
    if "monthly_bytes_downloaded" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN monthly_bytes_downloaded INTEGER NOT NULL DEFAULT 0")
    if "last_active_month" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN last_active_month TEXT")
    if "custom_quota_monthly_files" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN custom_quota_monthly_files INTEGER")
    if "custom_quota_monthly_bytes" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN custom_quota_monthly_bytes INTEGER")


def init_db() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with _db_lock:
        conn = _get_conn()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id            INTEGER PRIMARY KEY,
                is_approved        INTEGER NOT NULL DEFAULT 0,
                files_downloaded   INTEGER NOT NULL DEFAULT 0,
                bytes_downloaded   INTEGER NOT NULL DEFAULT 0,
                last_active_date   TEXT,
                custom_quota_files INTEGER,
                custom_quota_bytes INTEGER,
                default_quality    TEXT    NOT NULL DEFAULT '720',
                audio_mode         INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        _ensure_users_columns(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS download_events (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id          INTEGER NOT NULL,
                bytes_downloaded INTEGER NOT NULL,
                created_at       TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_download_events_user_created "
            "ON download_events(user_id, created_at)"
        )
        conn.commit()


def _normalize_username(username: str | None) -> str | None:
    if not username:
        return None
    value = username.strip().lstrip("@").lower()
    return value or None


def _normalize_display_name(display_name: str | None) -> str | None:
    if not display_name:
        return None
    value = re.sub(r"\s+", " ", display_name).strip()
    return value or None


def _now_utc_sql() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------

def add_user(user_id: int, approved: bool = False) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO users (user_id, is_approved) VALUES (?, ?)",
        (user_id, int(approved)),
    )
    conn.commit()


def touch_user_identity(user_id: int, username: str | None, display_name: str | None) -> None:
    uname = _normalize_username(username)
    dname = _normalize_display_name(display_name)
    conn = _get_conn()
    conn.execute(
        "INSERT INTO users (user_id, username, display_name) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET "
        "username=COALESCE(excluded.username, users.username), "
        "display_name=COALESCE(excluded.display_name, users.display_name)",
        (user_id, uname, dname),
    )
    conn.commit()


def approve_user(user_id: int) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT INTO users (user_id, is_approved) VALUES (?, 1) "
        "ON CONFLICT(user_id) DO UPDATE SET is_approved=1",
        (user_id,),
    )
    conn.commit()


def reject_user(user_id: int) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT INTO users (user_id, is_approved) VALUES (?, 0) "
        "ON CONFLICT(user_id) DO UPDATE SET is_approved=0",
        (user_id,),
    )
    conn.commit()


def set_user_approved(user_id: int, approved: bool) -> None:
    if approved:
        approve_user(user_id)
    else:
        reject_user(user_id)


def delete_user(user_id: int) -> None:
    conn = _get_conn()
    conn.execute("DELETE FROM users WHERE user_id=?", (user_id,))
    conn.commit()


def get_user(user_id: int) -> sqlite3.Row | None:
    conn = _get_conn()
    return conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()


def is_approved(user_id: int) -> bool:
    row = get_user(user_id)
    return bool(row and row["is_approved"])


def get_all_approved_users() -> list[int]:
    conn = _get_conn()
    rows = conn.execute("SELECT user_id FROM users WHERE is_approved=1").fetchall()
    return [r["user_id"] for r in rows]


def _user_search_where(query: str | None) -> tuple[str, list]:
    if not query:
        return "1=1", []
    q = query.strip()
    if not q:
        return "1=1", []
    if q.isdigit():
        return "user_id = ?", [int(q)]
    q = q.lstrip("@").lower()
    like = f"%{q}%"
    return (
        "(LOWER(COALESCE(username,'')) LIKE ? OR LOWER(COALESCE(display_name,'')) LIKE ?)",
        [like, like],
    )


def count_all_signed_users(query: str | None = None) -> int:
    where_sql, params = _user_search_where(query)
    conn = _get_conn()
    row = conn.execute(f"SELECT COUNT(*) AS c FROM users WHERE {where_sql}", params).fetchone()
    return int(row["c"] if row else 0)


def list_all_signed_users(page: int, per_page: int, query: str | None = None) -> list[sqlite3.Row]:
    page = max(page, 1)
    per_page = max(1, min(per_page, 50))
    offset = (page - 1) * per_page
    where_sql, params = _user_search_where(query)
    from config import ADMIN_ID
    conn = _get_conn()
    return conn.execute(
        f"""
        SELECT
            user_id, is_approved,
            files_downloaded, bytes_downloaded, last_active_date,
            custom_quota_files, custom_quota_bytes,
            username, display_name
        FROM users
        WHERE {where_sql}
        ORDER BY
            CASE WHEN user_id = ? THEN 0 ELSE 1 END,
            user_id DESC
        LIMIT ? OFFSET ?
        """,
        [*params, ADMIN_ID, per_page, offset],
    ).fetchall()


# ---------------------------------------------------------------------
# Quota helpers
# ---------------------------------------------------------------------

def set_custom_quota(user_id: int, files: int | None, bytes_: int | None) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT INTO users (user_id, custom_quota_files, custom_quota_bytes) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET custom_quota_files=excluded.custom_quota_files, "
        "custom_quota_bytes=excluded.custom_quota_bytes",
        (user_id, files, bytes_),
    )
    conn.commit()


def set_custom_quota_monthly(user_id: int, files: int | None, bytes_: int | None) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT INTO users (user_id, custom_quota_monthly_files, custom_quota_monthly_bytes) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET custom_quota_monthly_files=excluded.custom_quota_monthly_files, "
        "custom_quota_monthly_bytes=excluded.custom_quota_monthly_bytes",
        (user_id, files, bytes_),
    )
    conn.commit()


def get_effective_quota_bytes(user_id: int) -> int:
    from config import MAX_DAILY_BYTES

    row = get_user(user_id)
    if not row:
        return int(MAX_DAILY_BYTES)
    return int(row["custom_quota_bytes"]) if row["custom_quota_bytes"] is not None else int(MAX_DAILY_BYTES)


def get_effective_monthly_quota_bytes(user_id: int) -> int:
    from config import MAX_MONTHLY_BYTES

    row = get_user(user_id)
    if not row:
        return int(MAX_MONTHLY_BYTES)
    return int(row["custom_quota_monthly_bytes"]) if row["custom_quota_monthly_bytes"] is not None else int(MAX_MONTHLY_BYTES)


def get_effective_monthly_quota_files(user_id: int) -> int:
    from config import MAX_MONTHLY_FILES

    row = get_user(user_id)
    if not row:
        return int(MAX_MONTHLY_FILES)
    return int(row["custom_quota_monthly_files"]) if row["custom_quota_monthly_files"] is not None else int(MAX_MONTHLY_FILES)


def adjust_user_monthly_quota_bytes(user_id: int, delta_bytes: int) -> int:
    from config import MAX_MONTHLY_BYTES

    conn = _get_conn()
    conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    row = conn.execute("SELECT custom_quota_monthly_bytes FROM users WHERE user_id=?", (user_id,)).fetchone()
    base = int(row["custom_quota_monthly_bytes"]) if row and row["custom_quota_monthly_bytes"] is not None else int(MAX_MONTHLY_BYTES)
    new_bytes = max(0, base + int(delta_bytes))
    conn.execute("UPDATE users SET custom_quota_monthly_bytes=? WHERE user_id=?", (new_bytes, user_id))
    conn.commit()
    return new_bytes


def adjust_user_usage_count(user_id: int, delta: int) -> int:
    conn = _get_conn()
    today = date.today().isoformat()
    conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.execute(
        "UPDATE users SET files_downloaded=MAX(files_downloaded + ?, 0), last_active_date=? WHERE user_id=?",
        (int(delta), today, user_id),
    )
    conn.commit()
    row = conn.execute("SELECT files_downloaded FROM users WHERE user_id=?", (user_id,)).fetchone()
    return int(row["files_downloaded"] if row else 0)


def adjust_user_quota_bytes(user_id: int, delta_bytes: int) -> int:
    from config import MAX_DAILY_BYTES

    conn = _get_conn()
    conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    row = conn.execute("SELECT custom_quota_bytes FROM users WHERE user_id=?", (user_id,)).fetchone()
    base = int(row["custom_quota_bytes"]) if row and row["custom_quota_bytes"] is not None else int(MAX_DAILY_BYTES)
    new_bytes = max(0, base + int(delta_bytes))
    conn.execute("UPDATE users SET custom_quota_bytes=? WHERE user_id=?", (new_bytes, user_id))
    conn.commit()
    return new_bytes


# ---------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------

def update_setting(user_id: int, key: str, value) -> None:
    allowed = {"default_quality", "audio_mode"}
    if key not in allowed:
        raise ValueError(f"update_setting: unknown key '{key}'")
    conn = _get_conn()
    conn.execute(
        f"INSERT INTO users (user_id, {key}) VALUES (?, ?) "
        f"ON CONFLICT(user_id) DO UPDATE SET {key}=excluded.{key}",
        (user_id, value),
    )
    conn.commit()


# ---------------------------------------------------------------------
# Quota gate
# ---------------------------------------------------------------------

def check_and_update_quota(user_id: int, file_size_bytes: int) -> tuple[bool, str]:
    from config import MAX_DAILY_FILES, MAX_DAILY_BYTES, MAX_MONTHLY_FILES, MAX_MONTHLY_BYTES
    from locales import t
    from utils import fmt_size

    today_str = date.today().isoformat()
    month_str = date.today().strftime("%Y-%m")
    conn = _get_conn()

    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    if row is None:
        conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()

    # ── Daily reset ──────────────────────────────────────────────
    last_date = row["last_active_date"] or ""
    if last_date != today_str:
        conn.execute(
            "UPDATE users SET files_downloaded=0, bytes_downloaded=0, last_active_date=? WHERE user_id=?",
            (today_str, user_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()

    # ── Monthly reset ────────────────────────────────────────────
    last_month = row["last_active_month"] or ""
    if last_month != month_str:
        conn.execute(
            "UPDATE users SET monthly_files_downloaded=0, monthly_bytes_downloaded=0, last_active_month=? WHERE user_id=?",
            (month_str, user_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()

    # ── Daily limits ─────────────────────────────────────────────
    max_files = row["custom_quota_files"] if row["custom_quota_files"] is not None else MAX_DAILY_FILES
    max_bytes = row["custom_quota_bytes"] if row["custom_quota_bytes"] is not None else MAX_DAILY_BYTES

    files_used = row["files_downloaded"]
    bytes_used = row["bytes_downloaded"]

    if files_used >= max_files:
        return False, t(user_id, 'quota_files_exceeded',
                        used=files_used, max=max_files)

    if bytes_used + file_size_bytes > max_bytes:
        return False, t(user_id, 'quota_bytes_exceeded',
                        used=fmt_size(bytes_used), max=fmt_size(max_bytes))

    # ── Monthly limits ───────────────────────────────────────────
    max_monthly_files = row["custom_quota_monthly_files"] if row["custom_quota_monthly_files"] is not None else MAX_MONTHLY_FILES
    max_monthly_bytes = row["custom_quota_monthly_bytes"] if row["custom_quota_monthly_bytes"] is not None else MAX_MONTHLY_BYTES

    monthly_files_used = row["monthly_files_downloaded"]
    monthly_bytes_used = row["monthly_bytes_downloaded"]

    if monthly_files_used >= max_monthly_files:
        return False, t(user_id, 'quota_monthly_files_exceeded',
                        used=monthly_files_used, max=max_monthly_files)

    if monthly_bytes_used + file_size_bytes > max_monthly_bytes:
        return False, t(user_id, 'quota_monthly_bytes_exceeded',
                        used=fmt_size(monthly_bytes_used), max=fmt_size(max_monthly_bytes))

    # ── All checks passed — increment daily + monthly counters ──
    conn.execute(
        "UPDATE users SET files_downloaded=files_downloaded+1, "
        "bytes_downloaded=bytes_downloaded+?, last_active_date=?, "
        "monthly_files_downloaded=monthly_files_downloaded+1, "
        "monthly_bytes_downloaded=monthly_bytes_downloaded+?, last_active_month=? "
        "WHERE user_id=?",
        (file_size_bytes, today_str, file_size_bytes, month_str, user_id),
    )
    conn.commit()
    return True, ""


# ---------------------------------------------------------------------
# Download accounting
# ---------------------------------------------------------------------

def record_download_event(user_id: int, file_size_bytes: int, created_at: str | None = None) -> None:
    if file_size_bytes <= 0:
        return
    conn = _get_conn()
    conn.execute(
        "INSERT INTO download_events (user_id, bytes_downloaded, created_at) VALUES (?, ?, ?)",
        (user_id, int(file_size_bytes), created_at or _now_utc_sql()),
    )
    conn.commit()


def record_download_bytes(user_id: int, file_size_bytes: int) -> None:
    if file_size_bytes <= 0:
        return
    conn = _get_conn()
    conn.execute(
        "UPDATE users SET bytes_downloaded=bytes_downloaded+?, "
        "monthly_bytes_downloaded=monthly_bytes_downloaded+? WHERE user_id=?",
        (file_size_bytes, file_size_bytes, user_id),
    )
    conn.commit()
    record_download_event(user_id, file_size_bytes)


def get_user_download_stats(user_id: int) -> dict:
    now_local = datetime.now().astimezone()
    day_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start_local = day_start_local - timedelta(days=day_start_local.weekday())
    month_start_local = day_start_local.replace(day=1)

    def to_utc_sql(dt_local: datetime) -> str:
        return dt_local.astimezone(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")

    day_start_utc = to_utc_sql(day_start_local)
    week_start_utc = to_utc_sql(week_start_local)
    month_start_utc = to_utc_sql(month_start_local)

    conn = _get_conn()
    row = conn.execute(
        """
        SELECT
            SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS files_today,
            SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS files_week,
            SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS files_month,
            COUNT(*)                                         AS files_all,
            COALESCE(SUM(CASE WHEN created_at >= ? THEN bytes_downloaded ELSE 0 END), 0) AS bytes_today,
            COALESCE(SUM(CASE WHEN created_at >= ? THEN bytes_downloaded ELSE 0 END), 0) AS bytes_week,
            COALESCE(SUM(CASE WHEN created_at >= ? THEN bytes_downloaded ELSE 0 END), 0) AS bytes_month,
            COALESCE(SUM(bytes_downloaded), 0)                                          AS bytes_all
        FROM download_events
        WHERE user_id=?
        """,
        (
            day_start_utc,
            week_start_utc,
            month_start_utc,
            day_start_utc,
            week_start_utc,
            month_start_utc,
            user_id,
        ),
    ).fetchone()

    if row is None:
        return {
            "files_today": 0,
            "files_week": 0,
            "files_month": 0,
            "files_all": 0,
            "bytes_today": 0,
            "bytes_week": 0,
            "bytes_month": 0,
            "bytes_all": 0,
        }

    return {
        "files_today": int(row["files_today"] or 0),
        "files_week": int(row["files_week"] or 0),
        "files_month": int(row["files_month"] or 0),
        "files_all": int(row["files_all"] or 0),
        "bytes_today": int(row["bytes_today"] or 0),
        "bytes_week": int(row["bytes_week"] or 0),
        "bytes_month": int(row["bytes_month"] or 0),
        "bytes_all": int(row["bytes_all"] or 0),
    }


# ---------------------------------------------------------------------
# Global stats
# ---------------------------------------------------------------------

def get_global_stats() -> dict:
    conn = _get_conn()
    row = conn.execute(
        """
        SELECT
            COUNT(CASE WHEN is_approved = 1 THEN 1 END) AS total_approved,
            COALESCE(SUM(files_downloaded), 0)           AS total_files,
            COALESCE(SUM(bytes_downloaded), 0)           AS total_bytes
        FROM users
        """
    ).fetchone()
    if row is None:
        return {"total_approved": 0, "total_files": 0, "total_bytes": 0}
    return {
        "total_approved": row["total_approved"],
        "total_files": row["total_files"],
        "total_bytes": row["total_bytes"],
    }
