import json
import logging
import os
import tempfile
from typing import Any


def load_json_state(path: str, default: Any, logger: logging.Logger) -> Any:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        logger.warning("Ignoring corrupt JSON state file %s: %s", path, exc)
        return default
    except OSError as exc:
        logger.warning("Could not read JSON state file %s: %s", path, exc)
        return default


def save_json_state(path: str, state: Any) -> None:
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.",
        suffix=".tmp",
        dir=directory,
        text=True,
    )
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
