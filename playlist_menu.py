from telebot import types
from config import bot
from locales import t


def _show_playlist_menu(cid, message_id, mid, audio: bool):
    """Show the playlist quality selection menu."""
    if audio:
        _show_playlist_count_menu(cid, message_id, mid, audio=True, quality='audio')
    else:
        mk = types.InlineKeyboardMarkup(row_width=2)
        mk.add(
            types.InlineKeyboardButton("1080p",     callback_data=f"plq|1080|{mid}|0"),
            types.InlineKeyboardButton("720p",      callback_data=f"plq|720|{mid}|0"),
            types.InlineKeyboardButton("480p",      callback_data=f"plq|480|{mid}|0"),
            types.InlineKeyboardButton(t(cid, 'best_quality'), callback_data=f"plq|best|{mid}|0"),
        )
        try:
            bot.edit_message_text(t(cid, 'playlist_quality'), cid, message_id, reply_markup=mk)
        except Exception:
            pass


def _show_playlist_count_menu(cid, message_id, mid, audio: bool, quality: str):
    """Show the playlist item count selection menu."""
    a  = '1' if audio else '0'
    mk = types.InlineKeyboardMarkup(row_width=4)
    mk.add(
        types.InlineKeyboardButton("10",  callback_data=f"plcount|10|{mid}|{a}|{quality}"),
        types.InlineKeyboardButton("25",  callback_data=f"plcount|25|{mid}|{a}|{quality}"),
        types.InlineKeyboardButton("50",  callback_data=f"plcount|50|{mid}|{a}|{quality}"),
        types.InlineKeyboardButton("100", callback_data=f"plcount|100|{mid}|{a}|{quality}"),
    )
    mk.add(types.InlineKeyboardButton(
        t(cid, 'playlist_all_btn'), callback_data=f"plcount|9999|{mid}|{a}|{quality}"))
    mk.add(types.InlineKeyboardButton(
        t(cid, 'playlist_custom_btn'), callback_data=f"plcustom|{mid}|{a}|{quality}"))

    if audio:
        media_label = t(cid, 'playlist_media_audio')
    else:
        media_label = t(cid, 'playlist_media_video', quality=quality)

    try:
        bot.edit_message_text(
            t(cid, 'playlist_count_ask', media=media_label),
            cid, message_id, reply_markup=mk)
    except Exception:
        pass
