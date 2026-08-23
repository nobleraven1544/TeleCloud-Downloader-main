"""github_upload.py - Upload a file to the user's OWN GitHub repo using their
personal token (stored per-user in Postgres). Returns the raw download link.

Limits discovered by testing (GitHub Git Data API via JSON body):
  - base64 blob: works up to ~5MB, dies at 40MB
  - raw blob:    works up to ~39.5MB, dies at 40MB
=> Files >35MB are split into part files (name.ext.001, .002, ...) each <=35MB,
   uploaded as separate blobs. A companion .parts file lists the original name
   and chunk size so it can be rejoined.
"""

import os
import time
import base64
import threading
import requests

import db

GITHUB_DEFAULT_REPO = os.environ.get('GITHUB_DEFAULT_REPO', '')  # owner/repo fallback

API = "https://api.github.com"
CONTENTS_API_MAX = 20 * 1024 * 1024   # single-file limit (base64 blob) — safe margin
CHUNK_SIZE = 20 * 1024 * 1024         # part size for split uploads


def _hdrs(token: str) -> dict:
    return {"Authorization": f"token {token}",
            "Accept": "application/vnd.github+json"}


def _get_default_branch(token: str, repo: str) -> str:
    r = requests.get(f"{API}/repos/{repo}", headers=_hdrs(token), timeout=20)
    if r.status_code == 200:
        return r.json().get("default_branch", "main")
    return "main"


def _fmt_mb(n: int) -> str:
    return f"{n / (1024 * 1024):.1f}"


def _bar(pct: float, width: int = 14) -> str:
    filled = int(round(width * pct / 100))
    return "▓" * filled + "░" * (width - filled)


class ProgressReporter:
    """Edits a Telegram status message with live upload progress (MB + %)."""

    def __init__(self, status_msg, cid: int, fname: str, total: int):
        self.status_msg = status_msg
        self.cid = cid
        self.fname = fname
        self.total = max(total, 1)
        self.done = 0
        self._lock = threading.Lock()
        self._last_edit = 0.0

    def add(self, n: int):
        with self._lock:
            self.done = min(self.total, self.done + n)
            now = time.time()
            if now - self._last_edit >= 1.0 or self.done >= self.total:
                self._last_edit = now
                self._render()

    def _render(self):
        pct = self.done * 100 / self.total
        text = (f"🐙 آپلود به GitHub: {self.fname}\n"
                f"[{_bar(pct)}] {pct:.0f}%\n"
                f"📦 {_fmt_mb(self.done)} / {_fmt_mb(self.total)} MB")
        try:
            self.status_msg.edit_text(text)
        except Exception:
            pass


def _create_blob_raw(token: str, repo: str, data: bytes) -> dict:
    """Create a blob using base64 encoding (safe up to ~25MB raw)."""
    r = requests.post(f"{API}/repos/{repo}/git/blobs",
                      json={"content": base64.b64encode(data).decode(),
                            "encoding": "base64"},
                      headers=_hdrs(token), timeout=300)
    r.raise_for_status()
    return r.json()


def _commit_tree(token: str, repo: str, branch: str,
                 entries: list, message: str) -> None:
    """Commit a list of {'path','sha'} entries onto branch (fast-forward)."""
    r = requests.get(f"{API}/repos/{repo}/git/ref/heads/{branch}",
                     headers=_hdrs(token), timeout=20)
    r.raise_for_status()
    base_sha = r.json()["object"]["sha"]

    r = requests.get(f"{API}/repos/{repo}/git/commits/{base_sha}",
                     headers=_hdrs(token), timeout=20)
    r.raise_for_status()
    base_tree = r.json()["tree"]["sha"]

    tree_items = [{"path": e["path"], "mode": "100644", "type": "blob",
                   "sha": e["sha"]} for e in entries]
    r = requests.post(f"{API}/repos/{repo}/git/trees",
                      json={"base_tree": base_tree, "tree": tree_items},
                      headers=_hdrs(token), timeout=30)
    r.raise_for_status()
    new_tree = r.json()["sha"]

    r = requests.post(f"{API}/repos/{repo}/git/commits",
                      json={"message": message, "tree": new_tree,
                            "parents": [base_sha]},
                      headers=_hdrs(token), timeout=30)
    r.raise_for_status()
    new_commit = r.json()["sha"]

    r = requests.patch(f"{API}/repos/{repo}/git/refs/heads/{branch}",
                       json={"sha": new_commit}, headers=_hdrs(token), timeout=20)
    r.raise_for_status()


def _ensure_repo_ready(token: str, repo: str) -> bool:
    """Empty repos reject the Git Data API — seed with a tiny README once."""
    r = requests.get(f"{API}/repos/{repo}/commits?per_page=1",
                     headers=_hdrs(token), timeout=20)
    if r.status_code == 409 or (r.status_code == 200 and r.json() == []):
        from github import Github
        Github(token).get_repo(repo).create_file("README.md", "init", "# uploads\n")
        return True
    return False


def upload_to_github(file_path: str, user_id: int, status_msg=None) -> str | None:
    token = db.get_github_token(user_id)
    if not token:
        return None
    repo = db.get_github_repo(user_id) or GITHUB_DEFAULT_REPO
    if not repo:
        return None

    fname = os.path.basename(file_path)
    size = os.path.getsize(file_path)

    def _set_text(text):
        if status_msg:
            try:
                status_msg.edit_text(text)
            except Exception:
                pass

    reporter = ProgressReporter(status_msg, user_id, fname, size) if status_msg else None

    try:
        gh_branch = _get_default_branch(token, repo)
        _ensure_repo_ready(token, repo)

        if size <= CONTENTS_API_MAX:
            # Single file → one raw blob + commit
            _set_text(f"🐙 آپلود به GitHub: {fname}\n[{_bar(2)}] 2%\n"
                      f"📦 {_fmt_mb(size)} MB")
            with open(file_path, "rb") as f:
                data = f.read()
            blob = _create_blob_raw(token, repo, data)
            _commit_tree(token, repo, gh_branch,
                         [{"path": f"uploads/{user_id}/{fname}", "sha": blob["sha"]}],
                         f"upload {fname}")
            if reporter:
                reporter.add(len(data))
            return (f"https://raw.githubusercontent.com/{repo}/{gh_branch}/"
                    f"uploads/{user_id}/{fname}")

        # Large file → split into parts, upload each as its own blob
        n_parts = (size + CHUNK_SIZE - 1) // CHUNK_SIZE
        _set_text(f"🐙 آپلود به GitHub: {fname}\n"
                  f"📦 {_fmt_mb(size)} MB — به {n_parts} بخش تقسیم می‌شود\n[{_bar(0)}] 0%")

        entries = []
        with open(file_path, "rb") as f:
            for i in range(n_parts):
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                blob = _create_blob_raw(token, repo, chunk)
                entries.append({"path": f"uploads/{user_id}/{fname}.part{i+1:03d}",
                                "sha": blob["sha"]})
                if reporter:
                    reporter.add(len(chunk))

        # manifest so the parts can be reassembled
        import json as _json
        manifest = _json.dumps({"name": fname, "size": size, "parts": len(entries)})
        mblob = _create_blob_raw(token, repo, manifest.encode())
        entries.append({"path": f"uploads/{user_id}/{fname}.manifest.json",
                        "sha": mblob["sha"]})

        _commit_tree(token, repo, gh_branch, entries, f"upload {fname} ({n_parts} parts)")
        return (f"https://raw.githubusercontent.com/{repo}/{gh_branch}/"
                f"uploads/{user_id}/{fname}.part001")
    except Exception as e:
        print(f"[github] upload failed for user {user_id}: {e}")
        return None
