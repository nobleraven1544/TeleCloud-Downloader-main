"""
s3_upload.py - Upload a file to the Railway Bucket (S3-compatible) and return
a working download link.

Railway buckets are not served at RAILWAY_PUBLIC_DOMAIN directly, so we return
a presigned GET URL (valid 7 days). This works regardless of bucket privacy.
"""

import os
import time
import base64
import secrets
import boto3
from urllib.parse import quote
AWS_ENDPOINT_URL       = os.environ.get('AWS_ENDPOINT_URL', '')
AWS_ACCESS_KEY_ID      = os.environ.get('AWS_ACCESS_KEY_ID', '')
AWS_SECRET_ACCESS_KEY  = os.environ.get('AWS_SECRET_ACCESS_KEY', '')
AWS_DEFAULT_REGION     = os.environ.get('AWS_DEFAULT_REGION', 'auto')
AWS_BUCKET_NAME        = os.environ.get('AWS_BUCKET_NAME', '')


def _client():
    return boto3.client(
        "s3",
        endpoint_url=AWS_ENDPOINT_URL,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_DEFAULT_REGION,
    )


# ponytail: env-config cap; per-user quotas if this ever becomes a hotspot
BUCKET_MAX_BYTES = int(os.environ.get('BUCKET_MAX_GB', '5')) * 1024 ** 3


def _evict_oldest_if_full(client, incoming_bytes: int):
    """If bucket usage + incoming exceeds the cap, delete oldest objects
    until there's room. Keeps the newest files, evicts the oldest first."""
    try:
        paginator = client.get_paginator('list_objects_v2')
        objs = []
        total = 0
        for page in paginator.paginate(Bucket=AWS_BUCKET_NAME):
            for o in page.get('Contents', []):
                objs.append({'Key': o['Key'], 'Size': o['Size'],
                             'LastModified': o['LastModified']})
                total += o['Size']
        if total + incoming_bytes <= BUCKET_MAX_BYTES:
            return
        freed = 0
        need = total + incoming_bytes - BUCKET_MAX_BYTES
        for o in sorted(objs, key=lambda x: x['LastModified']):
            if freed >= need:
                break
            client.delete_object(Bucket=AWS_BUCKET_NAME, Key=o['Key'])
            freed += o['Size']
        print(f"[s3] evicted {freed/1e6:.0f}MB of old objects to make room")
    except Exception as e:
        print(f"[s3] evict failed (non-fatal): {e}")


def upload_to_s3(file_path: str, chat_id: int, status_msg=None) -> str | None:
    """Upload file_path to the bucket (encrypted with SSE-C), return a
    download URL. The per-file AES key rides in the URL fragment (#...),
    which browsers send to the proxy but S3-style servers ignore — privacy
    without a key database."""
    if not AWS_BUCKET_NAME:
        return None
    fname = os.path.basename(file_path)
    # object key: files/<chat_id>/<filename>
    key = f"files/{chat_id}/{fname}"

    client = _client()
    _evict_oldest_if_full(client, os.path.getsize(file_path))

    # Optional per-file password: if the user set one (/setpass), register a
    # PBKDF2 hash for this object key BEFORE uploading so the /files proxy
    # gates it. Import here to avoid circulars; failures are non-fatal.
    try:
        import file_passwords
        from handlers import get_pending_password
        pwd = get_pending_password(chat_id)
        if pwd:
            file_passwords.set_password(key, chat_id, pwd)
    except Exception as _pe:
        print(f"[s3] password gate skipped: {_pe}")

    # SSE-C: server-side encryption with a customer-provided per-file key.
    file_key = secrets.token_bytes(32)
    key_md5 = base64.b64encode(__import__('hashlib').md5(file_key).digest()).decode()

    # Live progress card: size, %, speed, ETA, elapsed — edited into status_msg
    total_bytes = os.path.getsize(file_path)
    up_start = time.time()
    last_edit = [0.0]
    from config import bot as _tg_bot

    def _s3_progress(n):
        import time as _t
        from utils import build_rich_progress_card, safe_tg_call
        now = _t.time()
        if now - last_edit[0] < 3 and n < total_bytes:
            return
        last_edit[0] = now
        done = min(n, total_bytes)
        pct = done / total_bytes * 100 if total_bytes else 100
        elapsed = max(now - up_start, 0.001)
        speed = done / elapsed
        eta = int((total_bytes - done) / speed) if speed > 0 else 0
        try:
            card = build_rich_progress_card(
                "🪣", fname, pct, done, total_bytes, speed, eta,
                "Direct link", "", cid=chat_id, started_at=up_start)
            safe_tg_call(_tg_bot.edit_message_text, card,
                         status_msg.chat.id, status_msg.message_id)
        except Exception:
            pass

    try:
        client.upload_file(
            file_path, AWS_BUCKET_NAME, key,
            Callback=_s3_progress,
            ExtraArgs={'SSECustomerAlgorithm': 'AES256',
                       'SSECustomerKey': base64.b64encode(file_key).decode(),
                       'SSECustomerKeyMD5': key_md5})
    except Exception as e:
        print(f"[s3] encrypted upload failed ({type(e).__name__}), falling back to plain: {e}")
        try:
            client.upload_file(file_path, AWS_BUCKET_NAME, key,
                               Callback=_s3_progress)
        except Exception as e2:
            print(f"[s3] upload failed: {e2}")
            return None
        file_key = None  # stored unencrypted

    # Custom public domain (PUBLIC_BASE_URL) → permanent pretty link via our
    # own proxy (which also enforces the optional per-file password).
    # Fallback: presigned URL (7 days), works regardless of bucket privacy.
    base = os.environ.get('PUBLIC_BASE_URL', '').strip().rstrip('/')
    frag = f"#k={base64.urlsafe_b64encode(file_key).decode()}" if file_key else ""

    # Presigned URL (7 days) — works regardless of bucket privacy. S3 signatures
    # only cover the Host header, so we can rewrite t3.storageapi.dev to
    # PUBLIC_BASE_URL and serve through our own proxy (bypasses Iran filtering).
    try:
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": AWS_BUCKET_NAME, "Key": key},
            ExpiresIn=7 * 24 * 3600,  # 7 days
        )
        if base:
            from urllib.parse import urlsplit, urlunsplit
            parts = list(urlsplit(url))
            parts[1] = urlsplit(base).netloc
            url = urlunsplit(parts)
        return url + frag
    except Exception as e:
        print(f"[s3] presign failed: {e}")
    if base:
        return f"{base}/files/{chat_id}/{quote(fname)}{frag}"

    # No PUBLIC_BASE_URL: if a password is set we MUST serve through the proxy
    # or the password gate would be meaningless — build the link from the
    # bot's own public domain instead of a presigned URL.
    import file_passwords
    if file_passwords.get_password(key):
        import os as _os
        dom = _os.environ.get('RAILWAY_PUBLIC_DOMAIN', '').strip()
        if dom:
            return f"https://{dom}/files/{chat_id}/{quote(fname)}{frag}"

    try:
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": AWS_BUCKET_NAME, "Key": key},
            ExpiresIn=7 * 24 * 3600,  # 7 days
        )
        return url + frag
    except Exception as e:
        print(f"[s3] presign failed: {e}")
        return None
