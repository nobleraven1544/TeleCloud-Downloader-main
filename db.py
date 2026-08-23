"""db.py - Postgres-backed user management for TeleCloud-Downloader (Railway).
Falls back to SQLite when DATABASE_URL is absent. Adds per-user GitHub token,
repo, upload-destination and monthly quota support.
"""

import os
import re
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_POSTGRES = bool(DATABASE_URL)
DB_PATH = "/app/user_configs/telecloud.db"

_local = threading.local()
_db_lock = threading.Lock()


def _get_conn():
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchall()
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            conn = None
    if conn is None:
        if USE_POSTGRES:
            _local.conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
            _local.conn.autocommit = False
        else:
            Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
            _local.conn = sqlite3_connect()
    return _local.conn


def sqlite3_connect():
    import sqlite3
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _sql(q: str) -> str:
    """Convert sqlite-style '?' placeholders to psycopg2 '%s' (no-op for sqlite)."""
    return q.replace("?", "%s") if USE_POSTGRES else q


def _run(q: str, params: tuple = ()):
    with _db_lock:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(_sql(q), params)
        conn.commit()
        return cur


def _fetchone(q: str, params: tuple = ()):
    with _db_lock:
        conn = _get_conn()
        if USE_POSTGRES:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        else:
            cur = conn.cursor()
            import sqlite3
            cur.row_factory = sqlite3.Row
        cur.execute(_sql(q), params)
        return cur.fetchone()


def _fetchall(q: str, params: tuple = ()):
    with _db_lock:
        conn = _get_conn()
        if USE_POSTGRES:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        else:
            cur = conn.cursor()
            import sqlite3
            cur.row_factory = sqlite3.Row
        cur.execute(_sql(q), params)
        return cur.fetchall()


# ----------------------------------------------------------------------
# Schema
# ----------------------------------------------------------------------

_PG_COLUMNS = [
    "username TEXT",
    "display_name TEXT",
    "monthly_files_downloaded INTEGER NOT NULL DEFAULT 0",
    "monthly_bytes_downloaded BIGINT NOT NULL DEFAULT 0",
    "last_active_month TEXT",
    "custom_quota_monthly_files INTEGER",
    "custom_quota_monthly_bytes BIGINT",
    "github_token TEXT",
    "github_repo TEXT",
    "upload_dest TEXT",
]

_SQLITE_COLUMNS = [
    "username TEXT",
    "display_name TEXT",
    "monthly_files_downloaded INTEGER NOT NULL DEFAULT 0",
    "monthly_bytes_downloaded INTEGER NOT NULL DEFAULT 0",
    "last_active_month TEXT",
    "custom_quota_monthly_files INTEGER",
    "custom_quota_monthly_bytes INTEGER",
    "github_token TEXT",
    "github_repo TEXT",
    "upload_dest TEXT",
]


def _ensure_users_columns(conn) -> None:
    cur = conn.cursor()
    if USE_POSTGRES:
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='users'")
        cols = {r[0] for r in cur.fetchall()}
    else:
        cur.execute("PRAGMA table_info(users)")
        cols = {r[1] for r in cur.fetchall()}
    adds = _PG_COLUMNS if USE_POSTGRES else _SQLITE_COLUMNS
    for col in adds:
        name = col.split()[0]
        if name not in cols:
            cur.execute(f"ALTER TABLE users ADD COLUMN {col}")
    conn.commit()


def init_db() -> None:
    with _db_lock:
        conn = _get_conn()
        cur = conn.cursor()
        pk = "BIGINT PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY"
        big = "BIGINT" if USE_POSTGRES else "INTEGER"
        autoinc = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS users (
                user_id            {pk},
                is_approved        INTEGER NOT NULL DEFAULT 0,
                files_downloaded   INTEGER NOT NULL DEFAULT 0,
                bytes_downloaded   {big} NOT NULL DEFAULT 0,
                last_active_date   TEXT,
                custom_quota_files INTEGER,
                custom_quota_bytes {big},
                default_quality    TEXT    NOT NULL DEFAULT '720',
                audio_mode         INTEGER NOT NULL DEFAULT 0
            )
        """)
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS download_events (
                id               {autoinc},
                user_id          {big} NOT NULL,
                bytes_downloaded {big} NOT NULL,
                created_at       TEXT NOT NULL
            )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_download_events_user_created "
            "ON download_events(user_id, created_at)")
        conn.commit()
        _ensure_users_columns(conn)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _normalize_username(username):
    if not username:
        return None
    value = str(username).strip().lstrip("@").lower()
    return value or None


def _normalize_display_name(display_name):
    if not display_name:
        return None
    value = re.sub(r"\s+", " ", str(display_name)).strip()
    return value or None


def _now_utc_sql() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ----------------------------------------------------------------------
# Users CRUD
# ----------------------------------------------------------------------

def add_user(user_id: int, approved: bool = False) -> None:
    _run(
        "INSERT INTO users (user_id, is_approved) VALUES (?, ?) "
        "ON CONFLICT(user_id) DO NOTHING",
        (user_id, int(approved)),
    )


def touch_user_identity(user_id: int, username, display_name) -> None:
    uname = _normalize_username(username)
    dname = _normalize_display_name(display_name)
    _run(
        "INSERT INTO users (user_id, username, display_name) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET "
        "username=COALESCE(excluded.username, users.username), "
        "display_name=COALESCE(excluded.display_name, users.display_name)",
        (user_id, uname, dname),
    )


def approve_user(user_id: int) -> None:
    _run("INSERT INTO users (user_id, is_approved) VALUES (?, 1) "
         "ON CONFLICT(user_id) DO UPDATE SET is_approved=1", (user_id,))


def reject_user(user_id: int) -> None:
    _run("INSERT INTO users (user_id, is_approved) VALUES (?, 0) "
         "ON CONFLICT(user_id) DO UPDATE SET is_approved=0", (user_id,))


def set_user_approved(user_id: int, approved: bool) -> None:
    approve_user(user_id) if approved else reject_user(user_id)


def delete_user(user_id: int) -> None:
    _run("DELETE FROM users WHERE user_id=?", (user_id,))


def get_user(user_id: int):
    return _fetchone("SELECT * FROM users WHERE user_id=?", (user_id,))


def is_approved(user_id: int) -> bool:
    row = get_user(user_id)
    return bool(row and row["is_approved"])


def get_all_approved_users() -> list:
    rows = _fetchall("SELECT user_id FROM users WHERE is_approved=1")
    return [r["user_id"] for r in rows]


def _user_search_where(query):
    if not query:
        return "1=1", []
    q = query.strip()
    if not q:
        return "1=1", []
    if q.isdigit():
        return "user_id = ?", [int(q)]
    q = q.lstrip("@").lower()
    like = f"%{q}%"
    return ("(LOWER(COALESCE(username,'')) LIKE ? OR LOWER(COALESCE(display_name,'')) LIKE ?)",
            [like, like])


def count_all_signed_users(query=None) -> int:
    where_sql, params = _user_search_where(query)
    row = _fetchone(f"SELECT COUNT(*) AS c FROM users WHERE {where_sql}", params)
    return int(row["c"] if row else 0)


def list_all_signed_users(page: int, per_page: int, query=None):
    page = max(page, 1)
    per_page = max(1, min(per_page, 50))
    offset = (page - 1) * per_page
    where_sql, params = _user_search_where(query)
    return _fetchall(
        f"""
        SELECT user_id, is_approved, files_downloaded, bytes_downloaded,
               last_active_date, custom_quota_files, custom_quota_bytes,
               username, display_name
        FROM users WHERE {where_sql}
        ORDER BY CASE WHEN user_id = ? THEN 0 ELSE 1 END, user_id DESC
        LIMIT ? OFFSET ?
        """,
        (*params, 0, per_page, offset),
    )


def set_custom_quota(user_id: int, files, bytes_) -> None:
    _run("UPDATE users SET custom_quota_files=?, custom_quota_bytes=? WHERE user_id=?",
         (files, bytes_, user_id))


def set_custom_quota_monthly(user_id: int, files, bytes_) -> None:
    _run("UPDATE users SET custom_quota_monthly_files=?, custom_quota_monthly_bytes=? "
         "WHERE user_id=?", (files, bytes_, user_id))


def get_effective_quota_bytes(user_id: int) -> int:
    from config import MAX_DAILY_BYTES
    row = get_user(user_id)
    if row and row["custom_quota_bytes"] is not None:
        return int(row["custom_quota_bytes"])
    return MAX_DAILY_BYTES


def get_effective_monthly_quota_bytes(user_id: int) -> int:
    from config import MAX_MONTHLY_BYTES
    row = get_user(user_id)
    if row and row["custom_quota_monthly_bytes"] is not None:
        return int(row["custom_quota_monthly_bytes"])
    return MAX_MONTHLY_BYTES


def get_effective_monthly_quota_files(user_id: int) -> int:
    from config import MAX_MONTHLY_FILES
    row = get_user(user_id)
    if row and row["custom_quota_monthly_files"] is not None:
        return int(row["custom_quota_monthly_files"])
    return MAX_MONTHLY_FILES


def adjust_user_monthly_quota_bytes(user_id: int, delta_bytes: int) -> int:
    row = get_user(user_id)
    used = int(row["monthly_bytes_downloaded"] or 0) if row else 0
    new_val = max(0, used + delta_bytes)
    _run("UPDATE users SET monthly_bytes_downloaded=? WHERE user_id=?", (new_val, user_id))
    return new_val


def adjust_user_usage_count(user_id: int, delta: int) -> int:
    row = get_user(user_id)
    used = int(row["files_downloaded"] or 0) if row else 0
    new_val = max(0, used + delta)
    _run("UPDATE users SET files_downloaded=? WHERE user_id=?", (new_val, user_id))
    return new_val


def adjust_user_quota_bytes(user_id: int, delta_bytes: int) -> int:
    row = get_user(user_id)
    used = int(row["bytes_downloaded"] or 0) if row else 0
    new_val = max(0, used + delta_bytes)
    _run("UPDATE users SET bytes_downloaded=? WHERE user_id=?", (new_val, user_id))
    return new_val


def update_setting(user_id: int, key: str, value) -> None:
    allowed = {"default_quality", "audio_mode"}
    if key not in allowed:
        raise ValueError(f"update_setting: unknown key '{key}'")
    _run(f"UPDATE users SET {key}=? WHERE user_id=?", (value, user_id))


# ----------------------------------------------------------------------
# GitHub token / repo & upload destination (per-user)
# ----------------------------------------------------------------------

def set_github_token(user_id: int, token: str) -> None:
    _run("UPDATE users SET github_token=? WHERE user_id=?", (token or "", user_id))


def get_github_token(user_id: int):
    row = get_user(user_id)
    if row and row.get("github_token"):
        return row["github_token"]
    return None


def set_github_repo(user_id: int, repo: str) -> None:
    _run("UPDATE users SET github_repo=? WHERE user_id=?", (repo or "", user_id))


def get_github_repo(user_id: int):
    row = get_user(user_id)
    if row and row.get("github_repo"):
        return row["github_repo"]
    return None


def set_upload_dest(user_id: int, dest: str) -> None:
    _run("UPDATE users SET upload_dest=? WHERE user_id=?", (dest, user_id))


def clear_upload_dest(user_id: int) -> None:
    set_upload_dest(user_id, None)


def get_upload_dest(user_id: int):
    row = get_user(user_id)
    if row:
        d = row.get("upload_dest")
        return d if d in ("gd", "s3", "github") else None
    return None


# ----------------------------------------------------------------------
# Quota gate
# ----------------------------------------------------------------------

def check_and_update_quota(user_id: int, file_size_bytes: int) -> tuple[bool, str]:
    from config import MAX_DAILY_FILES, MAX_DAILY_BYTES, MAX_MONTHLY_FILES, MAX_MONTHLY_BYTES

    today = date.today().isoformat()
    month = today[:7]

    row = get_user(user_id)
    if not row:
        return False, "not_registered"

    # Daily rollover
    if row["last_active_date"] != today:
        _run("UPDATE users SET last_active_date=?, files_downloaded=0, bytes_downloaded=0 "
             "WHERE user_id=?", (today, user_id))
        files_today, bytes_today = 0, 0
    else:
        files_today = int(row["files_downloaded"] or 0)
        bytes_today = int(row["bytes_downloaded"] or 0)

    # Monthly rollover
    if row["last_active_month"] != month:
        _run("UPDATE users SET last_active_month=?, monthly_files_downloaded=0, "
             "monthly_bytes_downloaded=0 WHERE user_id=?", (month, user_id))
        files_month, bytes_month = 0, 0
    else:
        files_month = int(row["monthly_files_downloaded"] or 0)
        bytes_month = int(row["monthly_bytes_downloaded"] or 0)

    eff_daily_files = (row["custom_quota_files"]
                       if row["custom_quota_files"] is not None else MAX_DAILY_FILES)
    eff_daily_bytes = (row["custom_quota_bytes"]
                       if row["custom_quota_bytes"] is not None else MAX_DAILY_BYTES)

    if files_today >= int(eff_daily_files):
        return False, "daily_files"
    if bytes_today + file_size_bytes > int(eff_daily_bytes):
        return False, "daily_bytes"
    if files_month >= get_effective_monthly_quota_files(user_id):
        return False, "monthly_files"
    if bytes_month + file_size_bytes > get_effective_monthly_quota_bytes(user_id):
        return False, "monthly_bytes"

    _run("""UPDATE users SET
              files_downloaded = files_downloaded + 1,
              bytes_downloaded = bytes_downloaded + ?,
              monthly_files_downloaded = monthly_files_downloaded + 1,
              monthly_bytes_downloaded = monthly_bytes_downloaded + ?,
              last_active_date = ?,
              last_active_month = ?
            WHERE user_id = ?""",
         (file_size_bytes, file_size_bytes, today, month, user_id))

    from config import MAX_MONTHLY_FILES
    return True, ""


def record_download_event(user_id: int, file_size_bytes: int, created_at: str | None = None) -> None:
    _run("INSERT INTO download_events (user_id, bytes_downloaded, created_at) VALUES (?, ?, ?)",
         (user_id, file_size_bytes, created_at or _now_utc_sql()))


def record_download_bytes(user_id: int, file_size_bytes: int) -> None:
    record_download_event(user_id, file_size_bytes)


def get_user_download_stats(user_id: int) -> dict:
    row = _fetchone("""
        SELECT
          COALESCE(SUM(CASE WHEN substr(created_at,1,10)=? THEN bytes_downloaded ELSE 0 END),0) AS bytes_today,
          COUNT(CASE WHEN substr(created_at,1,10)=? THEN 1 END) AS files_today,
          COALESCE(SUM(CASE WHEN substr(created_at,1,7)=? THEN bytes_downloaded ELSE 0 END),0) AS bytes_month,
          COUNT(CASE WHEN substr(created_at,1,7)=? THEN 1 END) AS files_month
        FROM download_events WHERE user_id=?
      """, (_now_utc_sql()[:10], _now_utc_sql()[:10], _now_utc_sql()[:7], _now_utc_sql()[:7], user_id))
    return dict(row) if row else {}


def get_global_stats() -> dict:
    row = _fetchone("""
        SELECT COUNT(*) AS total_users,
               SUM(CASE WHEN is_approved=1 THEN 1 ELSE 0 END) AS approved_users
        FROM users
      """)
    return dict(row) if row else {}
