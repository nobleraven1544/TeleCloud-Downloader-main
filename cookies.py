import os
import re
import threading
import logging
from urllib.parse import urlparse

from config import COOKIES_DIR, COOKIES_STATE
from json_state import load_json_state, save_json_state

logger = logging.getLogger(__name__)

# Serialises all read-modify-write operations on cookies_enabled.json.
# Without this lock, two concurrent Telegram callbacks can interleave
# their read/write and silently lose each other's changes.
_cookie_lock = threading.RLock()

# =============================================================
# Reading and writing cookie state
# =============================================================
def _cookies_state() -> dict:
    with _cookie_lock:
        state = load_json_state(COOKIES_STATE, {}, logger)
        if isinstance(state, dict):
            return state
        logger.warning("Ignoring non-object cookie state in %s", COOKIES_STATE)
        return {}

def _save_cookies_state(state: dict):
    with _cookie_lock:
        save_json_state(COOKIES_STATE, state)

# =============================================================
# Per-user cookie key helpers
# =============================================================
# Cookie files are stored as  <COOKIES_DIR>/<cid>_<name>.txt
# State JSON keys are          "<cid>:<name>"
# This ensures complete per-user isolation: no user can read,
# enable, disable, or accidentally overwrite another user's cookies.

def _file_key(cid, name: str) -> str:
    """Return the filename stem used for on-disk storage: '{cid}_{name}'."""
    return f"{cid}_{name}" if cid is not None else name

def _state_key(cid, name: str) -> str:
    """Return the key used inside cookies_enabled.json: '{cid}:{name}'."""
    return f"{cid}:{name}" if cid is not None else name

# =============================================================
# Cookie operations  (all accept an optional cid)
# =============================================================

def get_cookie_path(name: str, cid=None) -> str:
    return os.path.join(COOKIES_DIR, f"{_file_key(cid, name)}.txt")

def cookie_exists(name: str, cid=None) -> bool:
    p = get_cookie_path(name, cid)
    return os.path.exists(p) and os.path.getsize(p) > 0

def is_cookie_enabled(name: str, cid=None) -> bool:
    with _cookie_lock:
        return _cookies_state().get(_state_key(cid, name), True)

def set_cookie_enabled(name: str, val: bool, cid=None):
    with _cookie_lock:
        state = _cookies_state()
        state[_state_key(cid, name)] = val
        _save_cookies_state(state)

def delete_cookie(name: str, cid=None):
    with _cookie_lock:
        p = get_cookie_path(name, cid)
        if os.path.exists(p):
            os.remove(p)
        state = _cookies_state()
        state.pop(_state_key(cid, name), None)
        _save_cookies_state(state)

def save_cookie_data(name: str, data: bytes, cid=None):
    with _cookie_lock:
        with open(get_cookie_path(name, cid), 'wb') as f:
            f.write(data)
        state = _cookies_state()
        state[_state_key(cid, name)] = True
        _save_cookies_state(state)

def list_cookies(cid=None) -> list:
    """List cookies belonging to the given user (or all cookies if cid is None)."""
    with _cookie_lock:
        state  = _cookies_state()
        result = []
        prefix = f"{cid}_" if cid is not None else ""
        for fname in sorted(os.listdir(COOKIES_DIR)):
            if not fname.endswith('.txt'):
                continue
            stem = fname[:-4]  # strip .txt
            if cid is not None:
                # Only include this user's cookies
                if not stem.startswith(prefix):
                    continue
                name = stem[len(prefix):]
            else:
                name = stem
            path    = os.path.join(COOKIES_DIR, fname)
            enabled = state.get(_state_key(cid, name), True)
            size    = os.path.getsize(path)
            result.append({'name': name, 'path': path, 'enabled': enabled, 'size': size})
        return result

def active_cookies_file(url: str = '', cid=None) -> str:
    if url:
        try:
            domain = urlparse(url).netloc.lower()
            domain = re.sub(r'^www\.', '', domain)

            parts = domain.split('.')
            checks = []

            # Full domain underscored: music_youtube_com
            checks.append(domain.replace('.', '_'))

            # Progressively shorter from left: music_youtube, youtube
            for i in range(len(parts) - 1):
                checks.append('_'.join(parts[i:]))

            # Second-level domain only: youtube
            if len(parts) >= 2:
                checks.append(parts[-2])

            # x/twitter aliases
            aliases = {'x': ['x', 'twitter'], 'twitter': ['twitter', 'x']}
            final_checks = []
            for name in checks:
                final_checks.extend(aliases.get(name, [name]))

            for name in final_checks:
                if cookie_exists(name, cid) and is_cookie_enabled(name, cid):
                    return get_cookie_path(name, cid)
        except Exception:
            pass

    if cookie_exists('default', cid) and is_cookie_enabled('default', cid):
        return get_cookie_path('default', cid)
    return None
