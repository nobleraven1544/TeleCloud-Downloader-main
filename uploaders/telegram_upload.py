import os
from config import bot
from utils import fmt_size, cleanup_path, friendly_error, safe_tg_call
from uploaders.gdrive_upload import upload_to_gdrive_cancellable

_AUDIO_EXTS = ('.mp3', '.m4a', '.ogg', '.flac', '.wav')


def _clean_audio_meta(value, limit=64):
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    return value[:limit]


def _audio_metadata_for_telegram(file_path: str, task_info: dict, fallback_name: str):
    title = task_info.get('title')
    performer = task_info.get('artist') or task_info.get('performer')

    if not title or not performer:
        try:
            from mutagen import File as MutagenFile
            audio = MutagenFile(file_path, easy=True)
            if audio:
                title = title or (audio.get('title') or [None])[0]
                performer = performer or (audio.get('artist') or [None])[0]
        except Exception:
            pass

    return (
        _clean_audio_meta(title or os.path.splitext(fallback_name)[0]),
        _clean_audio_meta(performer),
    )


def upload_file_to_telegram(file_path: str, status_msg, task_info=None):
    from locales import t
    if task_info is None:
        task_info = {}
    chat_id = status_msg.chat.id
    cid     = chat_id

    # Fix 1: Fast-fail cancellation check — mirrors the pattern in youtube.py:352
    # and social.py:62. If the user already cancelled, bail out immediately before
    # touching the network or the file; the caller is responsible for cleanup.
    _stop = task_info.get('_stop')
    if _stop and _stop.is_set():
        return

    size_mb = os.path.getsize(file_path) / (1024 * 1024)

    if size_mb > 2000:
        try:
            safe_tg_call(
                bot.edit_message_text,
                t(cid, 'tg_upload_large', size=f"{size_mb:.1f}"),
                chat_id, status_msg.message_id)
        except Exception:
            pass
        upload_to_gdrive_cancellable(
            file_path, status_msg,
            task_info=task_info,
            user_id=task_info.get('user_id'),
        )
        return

    try:
        safe_tg_call(bot.edit_message_text, t(cid, 'tg_uploading'), chat_id, status_msg.message_id)
    except Exception:
        pass

    # Dynamic timeout: assume worst-case 1 MB/s upload speed, add 2-min buffer.
    # Floor of 300 s covers small files; ceiling is uncapped so 2 GB @ 1 MB/s
    # gets ~2168 s (~36 min) instead of the old hard-coded 300 s.
    _size_bytes    = os.path.getsize(file_path)
    upload_timeout = max(300, int(_size_bytes / (1 * 1024 * 1024)) + 120)

    try:
        with open(file_path, 'rb') as f:
            name = os.path.basename(file_path)
            ext  = os.path.splitext(name)[1].lower()
            # Caption: filename + origin line (e.g. "from Direct Link")
            source = (task_info or {}).get('source', '')
            caption = f"{name}\n🔗 از {source}" if source else name
            if ext in ('.mp4', '.mkv', '.avi', '.mov', '.webm'):
                bot.send_video(chat_id, f, caption=caption, timeout=upload_timeout)
            elif ext in _AUDIO_EXTS:
                audio_title, performer = _audio_metadata_for_telegram(file_path, task_info, name)
                kwargs = {'caption': caption, 'timeout': upload_timeout}
                if audio_title:
                    kwargs['title'] = audio_title
                if performer:
                    kwargs['performer'] = performer
                bot.send_audio(chat_id, f, **kwargs)
            else:
                bot.send_document(chat_id, f, caption=caption, timeout=upload_timeout)

        # Edit status message to show final success state
        title   = task_info.get('title', name)[:45]
        source  = task_info.get('source', 'Telegram')
        quality = task_info.get('quality', '')
        fsize   = fmt_size(os.path.getsize(file_path))

        final_text = t(cid, 'tg_upload_done',
                       title=title, size=fsize, source=source, quality=quality)
        try:
            safe_tg_call(bot.edit_message_text, final_text, chat_id, status_msg.message_id)
        except Exception:
            pass

        cleanup_path(file_path)
    except Exception as e:
        text = f"❌ {friendly_error(str(e), cid=cid)}"
        try:
            safe_tg_call(bot.edit_message_text, text, chat_id, status_msg.message_id)
        except Exception:
            safe_tg_call(bot.send_message, chat_id, text)

def upload_folder_to_telegram(folder_path: str, status_msg, task_info=None):
    from locales import t
    if task_info is None:
        task_info = {}
    chat_id = status_msg.chat.id
    cid     = chat_id
    if os.path.isfile(folder_path):
        upload_file_to_telegram(folder_path, status_msg, task_info)
        return
    files = sorted([os.path.join(folder_path, f)
                    for f in os.listdir(folder_path)
                    if os.path.isfile(os.path.join(folder_path, f))])
    bot.send_message(chat_id, t(cid, 'tg_folder_files', count=len(files)))

    # Fix 3: try/finally guarantees the entire folder_path is wiped from disk
    # whether the loop completes normally, breaks early on cancellation, or
    # raises. This prevents the storage leak where the parent directory and any
    # skipped/partially-uploaded files would otherwise remain on disk forever.
    _stop = task_info.get('_stop')
    try:
        for i, fp in enumerate(files, 1):
            # Fix 2: Per-iteration cancellation check. As soon as _stop is set
            # (user clicked Cancel), we break immediately so no new files are
            # started. upload_file_to_telegram's own Fix 1 guard also catches
            # the case where cancellation fires mid-iteration.
            if _stop and _stop.is_set():
                break
            sub = bot.send_message(chat_id, f"⬆️ {i}/{len(files)}: {os.path.basename(fp)}")
            upload_file_to_telegram(fp, sub, task_info)
    finally:
        # Wipes the parent folder and any remaining (skipped) files.
        # Individual successfully-uploaded files are already deleted by
        # upload_file_to_telegram's own cleanup_path(file_path) call, so this
        # is primarily a safety net for the directory entry and unprocessed files.
        cleanup_path(folder_path)


def send_split_parts(file_path: str, status_msg, task_info=None, part_mb: int = 40):
    """Split a large file into part_mb chunks and send each as a document.
    Parts are named <name>.part001, .part002 ... so the in-bot merge feature
    (🧩 چسباندن پارت‌ها) can reassemble them later."""
    import os
    import time
    from config import bot
    from utils import fmt_size, safe_tg_call

    chat_id = status_msg.chat.id
    cid     = chat_id
    if task_info is None:
        task_info = {}

    size      = os.path.getsize(file_path)
    part_size = part_mb * 1024 * 1024
    n_parts   = (size + part_size - 1) // part_size
    name      = os.path.basename(file_path)

    try:
        safe_tg_call(bot.edit_message_text,
                     f"✂️ تقسیم {name} ({fmt_size(size)}) به {n_parts} پارت...",
                     chat_id, status_msg.message_id)
    except Exception:
        pass

    sent = 0
    with open(file_path, 'rb') as f:
        i = 0
        while True:
            chunk = f.read(part_size)
            if not chunk:
                break
            i += 1
            part_name = f"{name}.part{i:03d}"
            from telebot.apihelper import ApiTelegramException
            bot.send_document(chat_id, chunk, visible_file_name=part_name,
                              caption=f"📦 {part_name} ({i}/{n_parts})",
                              timeout=max(300, len(chunk) // (1024 * 1024) + 120))
            sent = i
            try:
                safe_tg_call(bot.edit_message_text,
                             f"✂️ ارسال پارت {i}/{n_parts} از {name}",
                             chat_id, status_msg.message_id)
            except Exception:
                pass

    from utils import cleanup_path
    cleanup_path(file_path)
    try:
        safe_tg_call(bot.edit_message_text,
                     f"✅ {sent} پارت از {name} ارسال شد.\n"
                     "برای چسباندن پارت‌ها در ربات: منو ← 🧩 چسباندن پارت‌ها",
                     chat_id, status_msg.message_id)
    except Exception:
        pass


def merge_parts(parts: list, out_path: str, status_msg) -> bool:
    """Concatenate ordered part files into out_path with progress updates."""
    import os
    import time
    from config import bot
    from utils import fmt_size, safe_tg_call

    total   = sum(os.path.getsize(p) for p in parts)
    done    = 0
    last    = [0.0]
    t0      = time.time()

    with open(out_path, 'wb') as out:
        for idx, p in enumerate(parts, 1):
            with open(p, 'rb') as f:
                while True:
                    chunk = f.read(4 * 1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    now = time.time()
                    if now - last[0] > 3 or done >= total:
                        last[0] = now
                        pct = done / total * 100 if total else 100
                        elapsed = max(now - t0, 0.001)
                        speed = done / elapsed
                        eta = int((total - done) / speed) if speed else 0
                        try:
                            safe_tg_call(bot.edit_message_text,
                                         f"🧩 چسباندن پارت {idx}/{len(parts)}\n"
                                         f"[{'▓'*int(pct//5)}{'░'*(20-int(pct//5))}] {pct:.0f}%\n"
                                         f"📦 {fmt_size(done)} / {fmt_size(total)} • "
                                         f"⏱ ~{eta}s",
                                         status_msg.chat.id, status_msg.message_id)
                        except Exception:
                            pass
    return True
