import os
import threading
import logging

from config import USER_LANGS_FILE
from json_state import load_json_state, save_json_state

logger = logging.getLogger(__name__)

# In-memory cache to avoid repeated disk reads
_cache: dict = {}
_loaded = False
_lang_lock = threading.RLock()


def _load():
    global _loaded
    with _lang_lock:
        if _loaded:
            return
        _loaded = True
        if os.path.exists(USER_LANGS_FILE):
            data = load_json_state(USER_LANGS_FILE, {}, logger)
            if not isinstance(data, dict):
                logger.warning("Ignoring non-object language state in %s", USER_LANGS_FILE)
                return
            for k, v in data.items():
                try:
                    _cache[int(k)] = v
                except (TypeError, ValueError):
                    logger.warning("Ignoring invalid language user id %r", k)


def _save():
    with _lang_lock:
        try:
            save_json_state(USER_LANGS_FILE, {str(k): v for k, v in _cache.items()})
        except OSError as exc:
            logger.warning("Could not save language state %s: %s", USER_LANGS_FILE, exc)


def get_lang(cid: int) -> str:
    """Return the user's language code ('fa' or 'en'). Defaults to 'fa'."""
    with _lang_lock:
        _load()
        return _cache.get(cid, 'fa')


def has_lang(cid: int) -> bool:
    """Return True if the user has already chosen a language."""
    with _lang_lock:
        _load()
        return cid in _cache


def set_lang(cid: int, lang: str):
    """Persist the user's language choice."""
    with _lang_lock:
        _load()
        _cache[cid] = lang
        _save()
