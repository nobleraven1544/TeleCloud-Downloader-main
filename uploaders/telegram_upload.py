import os
import time
import subprocess
import tempfile
from config import bot
from utils import fmt_size, cleanup_path, friendly_error, safe_tg_call
from uploaders.gdrive_upload import upload_to_gdrive_cancellable

_AUDIO_EXTS = ('.mp3', '.m4a', '.ogg', '.flac', '.wav')
_TELEGRAM_MAX = 48 * 1024 * 1024  # 48MB safe limit (Bot API = 50MB)


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


def _upload_split(file_path: str, status_msg, task_info=None):
    """Split a large file into <=48MB chunks and upload each as a document."""
    from locales import t
    chat_id = status_msg.chat.id
    cid     = chat_id
    name    = os.path.basename(file_path)
    total   = os.path.getsize(file_path)
    chunk_n = (total // _TELEGRAM_MAX) + 1
    base, ext = os.path.splitext(name)
    tmp_dir   = tempfile.mkdtemp(prefix="split_")

    try:
        # Use ffmpeg for video/audio split (preserves playback), binary split for others
        video_exts = ('.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv')
        audio_exts = ('.mp3', '.m4a', '.ogg', '.flac', '.wav')
        is_media = ext.lower() in video_exts + audio_exts

        if is_media:
            # Calculate duration-based split points
            dur_r = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', file_path],
                capture_output=True, text=True, timeout=30)
            total_dur = float(dur_r.stdout.strip()) if dur_r.returncode == 0 else 0
            part_dur  = total_dur / chunk_n if total_dur else 0

            for i in range(chunk_n):
                part_name = f"{base}_part{i+1:02d}{ext}"
                part_path = os.path.join(tmp_dir, part_name)
                start = i * part_dur
                cmd = ['ffmpeg', '-y', '-ss', str(start), '-i', file_path,
                       '-t', str(part_dur), '-c', 'copy', '-avoid_negative_ts', 'make_zero', part_path]
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        else:
            # Binary split for non-media files
            with open(file_path, 'rb') as src:
                for i in range(chunk_n):
                    part_name = f"{base}_part{i+1:02d}{ext}"
                    part_path = os.path.join(tmp_dir, part_name)
                    chunk = src.read(_TELEGRAM_MAX)
                    if chunk:
                        with open(part_path, 'wb') as dst:
                            dst.write(chunk)

        parts = sorted([os.path.join(tmp_dir, f) for f in os.listdir(tmp_dir)
                        if os.path.isfile(os.path.join(tmp_dir, f))])

        _stop = task_info.get('_stop') if task_info else None
        for i, part in enumerate(parts, 1):
            if _stop and _stop.is_set():
                break
            part_size = fmt_size(os.path.getsize(part))
            part_name = os.path.basename(part)
            sub = bot.send_message(chat_id,
                                   f"📦 {i}/{len(parts)}: {part_name} ({part_size})")
            try:
                with open(part, 'rb') as f:
                    bot.send_document(chat_id, f,
                                      caption=f"{part_name} [{i}/{len(parts)}]",
                                      timeout=600)
            except Exception as e:
                bot.send_message(chat_id, f"❌ {i}/{len(parts)}: {friendly_error(str(e), cid=cid)}")

        # Final message
        final = f"✅ ارسال {len(parts)} پارت از {name} ({fmt_size(total)}) تمام شد"
        try:
            safe_tg_call(bot.edit_message_text, final, chat_id, status_msg.message_id)
        except Exception:
            bot.send_message(chat_id, final)

        cleanup_path(file_path)
    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)


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

    # Files between 50MB and 2GB: split into chunks for Telegram Bot API
    if os.path.getsize(file_path) > _TELEGRAM_MAX:
        try:
            safe_tg_call(bot.edit_message_text,
                         t(cid, 'tg_uploading') + f" (split {size_mb:.0f}MB)",
                         chat_id, status_msg.message_id)
        except Exception:
            pass
        _upload_split(file_path, status_msg, task_info)
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
                # Generate a preview thumbnail with ffmpeg so the media shows
                # a real frame instead of a generic/blank preview.
                thumb_path = None
                try:
                    import subprocess as _sp, tempfile as _tf
                    _t = os.path.join(_tf.gettempdir(), f"thumb_{os.getpid()}_{int(time.time())}.jpg")
                    r = _sp.run(['ffmpeg', '-y', '-ss', '3', '-i', file_path,
                                 '-frames:v', '1', '-vf', 'scale=320:-2', _t],
                                stdout=_sp.DEVNULL, stderr=_sp.DEVNULL, timeout=60)
                    if r.returncode == 0 and os.path.getsize(_t) > 0:
                        thumb_path = _t
                except Exception:
                    thumb_path = None
                # supports_streaming lets Telegram play the video inline
                # (progressive watch) instead of requiring a full download.
                kwargs = {'caption': caption, 'supports_streaming': True,
                          'timeout': upload_timeout}
                if thumb_path:
                    kwargs['thumbnail'] = open(thumb_path, 'rb')
                bot.send_video(chat_id, f, **kwargs)
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
