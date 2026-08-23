"""github_upload.py - Upload a file to the user's OWN GitHub repo using their
personal token (stored per-user in Postgres). Returns the raw download link.

Small files (<45 MB) go through the Contents API.
Larger files use the Git Data API (blob + commit) which supports up to 100 MB.
Live progress (MB + %) is edited into the Telegram status message.
"""

import os
import time
import base64
import threading
import requests

import db

GITHUB_DEFAULT_REPO = os.environ.get('GITHUB_DEFAULT_REPO', '')  # owner/repo fallback

API = "https://api.github.com"
CONTENTS_API_MAX = 45 * 1024 * 1024  # stay under GitHub's ~50MB contents limit


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
        self.cancelled = threading.Event()
        self._lock = threading.Lock()
        self._last_edit = 0.0

    def add(self, n: int):
        with self._lock:
            self.done = min(self.total, self.done + n)
            now = time.time()
            # throttle edits to ~1/sec so Telegram doesn't rate-limit us
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


def _chunked_read(file_path: str, chunk_size: int, reporter: "ProgressReporter"):
    """Yield file chunks while reporting live progress; abort on cancel."""
    with open(file_path, "rb") as f:
        while True:
            if reporter.cancelled.is_set():
                raise InterruptedError("cancelled")
            chunk = f.read(chunk_size)
            if not chunk:
                break
            reporter.add(len(chunk))
            yield chunk


def _create_tree_with_file(token: str, repo: str, path: str, blob_sha: str) -> str:
    r = requests.post(f"{API}/repos/{repo}/git/trees",
                      json={"tree": [{"path": path, "mode": "100644",
                                      "type": "blob", "sha": blob_sha}]},
                      headers=_hdrs(token), timeout=30)
    r.raise_for_status()
    return r.json()["sha"]


def _upload_small(repository, path: str, fname: str, content: bytes) -> None:
    try:
        existing = repository.get_contents(path)
        repository.update_file(path, f"upload {fname}", content, existing.sha)
    except Exception:
        repository.create_file(path, f"upload {fname}", content)


def _upload_large(token: str, repo: str, path: str, fname: str,
                  file_path: str, branch: str, reporter: "ProgressReporter") -> None:
    """Git Data API route: blob → commit → fast-forward ref (up to 100MB)."""
    # An empty repo rejects blob creation with 409; seed it via Contents API.
    r_probe = requests.get(f"{API}/repos/{repo}/commits?per_page=1",
                           headers=_hdrs(token), timeout=20)
    is_empty = (r_probe.status_code == 409
                or (r_probe.status_code == 200 and r_probe.json() == []))
    if is_empty:
        # Empty repo: Git Data API refuses blobs (409). Seed the repo with a
        # tiny README via Contents API, then continue with the Git Data flow.
        from github import Github
        repository = Github(token).get_repo(repo)
        repository.create_file("README.md", "init", "# uploads\n")
        reporter.add(0)  # keep progress at 0 for the real file

    # Stream the file as a single multipart-style PUT via chunked generator so
    # progress updates flow while the request body is being sent.
    total = reporter.total
    gen = _chunked_read(file_path, 512 * 1024, reporter)
    body = b"".join(gen)  # consumed fully; progress already reported per chunk
    r = requests.post(f"{API}/repos/{repo}/git/blobs",
                      json={"content": base64.b64encode(body).decode(),
                            "encoding": "base64"},
                      headers=_hdrs(token), timeout=300)
    r.raise_for_status()
    blob_sha = r.json()["sha"]

    # Get current head commit + tree
    r = requests.get(f"{API}/repos/{repo}/git/ref/heads/{branch}",
                     headers=_hdrs(token), timeout=20)
    r.raise_for_status()
    base_sha = r.json()["object"]["sha"]

    r = requests.get(f"{API}/repos/{repo}/git/commits/{base_sha}",
                     headers=_hdrs(token), timeout=20)
    r.raise_for_status()
    base_tree = r.json()["tree"]["sha"]

    r = requests.post(f"{API}/repos/{repo}/git/trees",
                      json={"base_tree": base_tree,
                            "tree": [{"path": path, "mode": "100644",
                                      "type": "blob", "sha": blob_sha}]},
                      headers=_hdrs(token), timeout=30)
    r.raise_for_status()
    new_tree = r.json()["sha"]

    r = requests.post(f"{API}/repos/{repo}/git/commits",
                      json={"message": f"upload {fname}", "tree": new_tree,
                            "parents": [base_sha]},
                      headers=_hdrs(token), timeout=30)
    r.raise_for_status()
    new_commit = r.json()["sha"]

    r = requests.patch(f"{API}/repos/{repo}/git/refs/heads/{branch}",
                       json={"sha": new_commit}, headers=_hdrs(token), timeout=20)
    r.raise_for_status()


def upload_to_github(file_path: str, user_id: int, status_msg=None) -> str | None:
    """Upload file_path to the user's GitHub repo, return raw URL or None."""
    token = db.get_github_token(user_id)
    if not token:
        return None
    repo = db.get_github_repo(user_id) or GITHUB_DEFAULT_REPO
    if not repo:
        return None

    fname = os.path.basename(file_path)
    size = os.path.getsize(file_path)

    reporter = ProgressReporter(status_msg, user_id, fname, size) if status_msg else None

    def _set_text(text):
        if not status_msg:
            return
        try:
            status_msg.edit_text(text)
        except Exception:
            pass

    try:
        gh_branch = _get_default_branch(token, repo)
        path = f"uploads/{user_id}/{fname}"

        if size <= CONTENTS_API_MAX:
            _set_text(f"🐙 آپلود به GitHub: {fname}\n[{_bar(5)}] 5%\n"
                      f"📦 {_fmt_mb(size)} MB — در حال آماده‌سازی...")
            from github import Github
            gh = Github(token)
            repository = gh.get_repo(repo)
            with open(file_path, "rb") as f:
                content = f.read()
            if reporter:
                reporter.add(len(content))
            _upload_small(repository, path, fname, content)
        else:
            _set_text(f"🐙 آپلود به GitHub: {fname}\n[{_bar(0)}] 0%\n"
                      f"📦 0.0 / {_fmt_mb(size)} MB")
            _upload_large(token, repo, path, fname, file_path, gh_branch, reporter)

        return f"https://raw.githubusercontent.com/{repo}/{gh_branch}/{path}"
    except Exception as e:
        print(f"[github] upload failed for user {user_id}: {e}")
        if reporter and reporter.cancelled.is_set():
            _set_text("🚫 آپلود لغو شد.")
        return None
