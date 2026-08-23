import os
from config import bot
from utils import get_file_size, fmt_size

def smart_dest(file_path: str, status_msg, dest: str = None, folder_name: str = None, task_info: dict = None):
    """
    Send the file to the correct destination.
    dest='tg'  → Telegram (auto-redirects to Drive if size > 2GB)
    dest='gd'  → Google Drive
    dest=None  → reads from user's upload toggle
    """
    from locales import t
    from config import tg_upload_mode
    from uploaders.telegram_upload import upload_file_to_telegram
    from uploaders.gdrive_upload import upload_to_gdrive_cancellable

    chat_id = status_msg.chat.id
    cid     = chat_id
    if task_info is None:
        task_info = {}

    if dest is None:
        dest = 'tg' if chat_id in tg_upload_mode else 'gd'

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
    else:
        user_id = task_info.get('user_id')
        upload_to_gdrive_cancellable(
            file_path, status_msg,
            folder_name=folder_name,
            task_info=task_info,
            user_id=user_id,
        )