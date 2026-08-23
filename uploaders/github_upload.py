"""
github_upload.py - Upload a file to the user's OWN GitHub repo using their
personal token (stored per-user in Postgres). Returns the raw download link.

Small files (<50 MB after base64 ~ <37 MB raw) go through the Contents API.
Larger files are uploaded via the Git Data API (blobs + commit) which supports
files up to 100 MB, avoiding the 422 "file is too large" error of Contents API.
"""

import os
import base64
import json
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


def _upload_small(repository, path: str, fname: str, content: bytes, token: str) -> None:
    try:
        existing = repository.get_contents(path)
        repository.update_file(path, f"upload {fname}", content, existing.sha)
    except Exception:
        repository.create_file(path, f"upload {fname}", content)


def _create_tree_with_file(token: str, repo: str, path: str, blob_sha: str) -> str:
    r = requests.post(f"{API}/repos/{repo}/git/trees",
                      json={"tree": [{"path": path, "mode": "100644",
                                      "type": "blob", "sha": blob_sha}]},
                      headers=_hdrs(token), timeout=30)
    r.raise_for_status()
    return r.json()["sha"]


def _upload_large(token: str, repo: str, path: str, fname: str,
                  file_path: str, branch: str) -> None:
    """Git Data API route: blob → commit → fast-forward ref (handles up to 100MB)."""
    with open(file_path, "rb") as f:
        data = f.read()

    # An empty repo rejects blob creation with 409; seed it via Contents API.
    r_probe = requests.get(f"{API}/repos/{repo}/commits?per_page=1",
                           headers=_hdrs(token), timeout=20)
    is_empty = (r_probe.status_code == 409
                or (r_probe.status_code == 200 and r_probe.json() == []))
    if is_empty:
        from github import Github
        repository = Github(token).get_repo(repo)
        repository.create_file(path, f"upload {fname}", data)
        return

    r = requests.post(f"{API}/repos/{repo}/git/blobs",
                      json={"content": base64.b64encode(data).decode(),
                            "encoding": "base64"},
                      headers=_hdrs(token), timeout=120)
    r.raise_for_status()
    blob_sha = r.json()["sha"]

    # Get current head commit + tree
    r = requests.get(f"{API}/repos/{repo}/git/ref/heads/{branch}",
                     headers=_hdrs(token), timeout=20)
    if r.status_code == 404:
        # empty repo — create first commit from scratch
        r = requests.post(f"{API}/repos/{repo}/git/commits",
                          json={"message": f"upload {fname}",
                                "tree": _create_tree_with_file(token, repo, path, blob_sha),
                                "parents": []},
                          headers=_hdrs(token), timeout=30)
        r.raise_for_status()
        commit_sha = r.json()["sha"]
        requests.post(f"{API}/repos/{repo}/git/refs",
                      json={"ref": f"refs/heads/{branch}", "sha": commit_sha},
                      headers=_hdrs(token), timeout=20).raise_for_status()
        return
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
    try:
        gh_branch = _get_default_branch(token, repo)
        path = f"uploads/{user_id}/{fname}"
        if size <= CONTENTS_API_MAX:
            from github import Github
            gh = Github(token)
            repository = gh.get_repo(repo)
            with open(file_path, "rb") as f:
                content = f.read()
            _upload_small(repository, path, fname, content, token)
        else:
            _upload_large(token, repo, path, fname, file_path, gh_branch)
        return f"https://raw.githubusercontent.com/{repo}/{gh_branch}/{path}"
    except Exception as e:
        print(f"[github] upload failed for user {user_id}: {e}")
        return None
