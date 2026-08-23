import os
from config import bot
from utils import get_file_size, fmt_size


def smart_dest(file_path: str, status_msg, dest: str = None, folder_name: str = None, task_info: dict = None):
    """
    Send the file to the correct destination.
    dest='tg'      → Telegram (auto-redirects to Drive if size > 2GB)
    dest='gd'      → Google Drive (per-user rclone config)
    dest='s3'      → Railway Bucket (S3-compatible), presigned link
    dest='github'  → user's own GitHub repo (per-user token), raw link
    dest=None      → reads from user's saved upload_dest, else Telegram
    """
    from locales import t
    from config import tg_upload_mode
    from uploaders.telegram_upload import upload_file_to_telegram
    from uploaders.gdrive_upload import upload_to_gdrive_cancellable
    from uploaders.github_upload import upload_to_github

    chat_id = status_msg.chat.id
    cid     = chat_id
    if task_info is None:
        task_info = {}

    if dest is None:
        try:
            import db
            d = db.get_upload_dest(cid)
            dest = d if d in ('s3', 'github', 'gd') else 'tg'
        except Exception:
            dest = 'tg'
        if dest == 'gd' and cid in tg_upload_mode:
            dest = 'tg'

    # If Drive chosen but user has no rclone config → fall back to Telegram
    if dest == 'gd':
        from pathlib import Path
        from config import USER_CONFIGS_DIR
        if not Path(USER_CONFIGS_DIR, f"rclone_{cid}.conf").exists():
            try:
                bot.edit_message_text(
                    "☁️ گوگل درایو وصل نیست — فایل به تلگرام ارسال شد. "
                    "برای آپلود به Drive/S3/GitHub از تنظیمات مقصد را عوض کن.",
                    chat_id, status_msg.message_id,
                )
            except Exception:
                pass
            dest = 'tg'

    size = get_file_size(file_path)

    # Prevent sending a new message for large files destined for Telegram
    if size > 2000 * 1024 * 1024 and dest == 'tg':
        try:
            bot.edit_message_text(
                t(cid, 'smart_dest_large', size=fmt_size(size)),
                chat_id, status_msg.message_id
            )
        except Exception:
            pass
        dest = 'gd'

    if dest == 'tg':
        upload_file_to_telegram(file_path, status_msg, task_info)
    elif dest == 'github':
        url = upload_to_github(file_path, cid, status_msg)
        _reply_link(status_msg, url, "GitHub", cid)
    elif dest == 's3':
        from uploaders.s3_upload import upload_to_s3
        url = upload_to_s3(file_path, cid, status_msg)
        _reply_link(status_msg, url, "S3/Railway", cid)
    else:
        user_id = task_info.get('user_id')
        upload_to_gdrive_cancellable(
            file_path, status_msg,
            folder_name=folder_name,
            task_info=task_info,
            user_id=user_id,
        )


def _reply_link(status_msg, url: str, label: str, cid: int):
    """Send the download link after a cloud upload (or an error notice)."""
    from locales import t
    if url:
        try:
            status_msg.edit_text(f"✅ آپلود به {label} انجام شد:\n{url}",
                                 disable_web_page_preview=True)
        except Exception:
            from config import bot
            bot.send_message(cid, f"✅ آپلود به {label} انجام شد:\n{url}",
                             disable_web_page_preview=True)
    else:
        try:
            status_msg.edit_text(
                f"❌ خطا در آپلود به {label}. دوباره امتحان کن یا مقصد دیگه‌ای انتخاب کن.")
        except Exception:
            pass
