import time
import threading
import logging
from concurrent.futures import ThreadPoolExecutor
from collections import Counter

from config import bot, MAX_RETRIES, RETRY_DELAY, MAX_CONCURRENT_DOWNLOADS
from utils import friendly_error
import config

logger = logging.getLogger(__name__)

# The single shared executor; initialised by start_worker().
_executor: ThreadPoolExecutor | None = None
_dispatcher_thread: threading.Thread | None = None
_dispatcher_stop = threading.Event()
_worker_lock = threading.RLock()

# Round-robin cursor (chat_id of the last dispatched task).
# Accessed only by the single dispatcher thread.
_rr_last_chat_id = None


# =============================================================
# Internal: execute one task inside a pool worker thread
# =============================================================
def _run_task(task: dict) -> None:
    """
    Execute a single download task.

    Lifecycle
    ---------
    1. Register the task in config.current_tasks so cancel/status
       queries can find it.
    2. Dispatch to the appropriate downloader.
    3. On failure, retry up to MAX_RETRIES times (with RETRY_DELAY
       seconds between attempts) unless the user explicitly cancelled.
    4. Always deregister from config.current_tasks in the finally block.
    """
    cid     = task.get('chat_id')
    retries = task.get('_retries', 0)

    # Use the task object's identity as a unique key.
    # id(task) is stable for the entire lifetime of this call because
    # _run_task holds a reference on its stack, preventing GC/reuse.
    _task_id = id(task)

    # Register as an active task so status queries and cancellation can find it
    with config.current_tasks_lock:
        config.current_tasks[_task_id] = task

    try:
        _dispatch(task)

    except Exception as e:
        err       = str(e)
        from locales import t
        cancel_kw = t(cid, 'cancelled_keyword') if cid else "لغو"

        if retries < MAX_RETRIES and cancel_kw not in err:
            task['_retries'] = retries + 1
            try:
                bot.send_message(
                    cid,
                    t(cid, 'retry_error',
                      attempt=retries + 1, max=MAX_RETRIES,
                      error=friendly_error(err, cid=cid),
                      delay=RETRY_DELAY) if cid else (
                        f"⚠️ خطا در دانلود (تلاش {retries+1}/{MAX_RETRIES}):\n"
                        f"{friendly_error(err)}\n\n"
                        f"⏳ {RETRY_DELAY} ثانیه دیگر دوباره امتحان میکنم..."
                    )
                )
            except Exception:
                pass
            # Re-enqueue after delay (the dispatcher will inject a fresh _stop)
            threading.Timer(RETRY_DELAY, lambda t=task: enqueue(t)).start()

        else:
            try:
                if retries >= MAX_RETRIES:
                    bot.send_message(
                        cid,
                        t(cid, 'max_retries_error',
                          max=MAX_RETRIES,
                          error=friendly_error(err, cid=cid)) if cid else (
                            f"❌ بعد از {MAX_RETRIES} بار تلاش موفق نشدم:\n{friendly_error(err)}"
                        )
                    )
                else:
                    bot.send_message(
                        cid,
                        t(cid, 'generic_error',
                          error=friendly_error(err, cid=cid)) if cid else (
                            f"❌ خطا:\n{friendly_error(err)}"
                        )
                    )
            except Exception:
                pass

    finally:
        # Always deregister, even if the task was retried
        with config.current_tasks_lock:
            config.current_tasks.pop(_task_id, None)


# =============================================================
# Internal: dispatcher thread — feeds tasks into the pool
# =============================================================
def _snapshot_active_by_chat() -> tuple[int, Counter]:
    """
    Return:
      1) total number of active running tasks
      2) per-chat active task counts

    This function only holds current_tasks_lock and never touches queue_lock.
    """
    with config.current_tasks_lock:
        active_tasks = list(config.current_tasks.values())

    counts = Counter(tk.get('chat_id') for tk in active_tasks)
    return len(active_tasks), counts


def _pick_fair_pending_index(pending_queue: list, active_by_chat: Counter) -> int | None:
    """
    Pick one task index from pending_queue using user-based fairness:
      1) Prefer chat_id(s) with the lowest currently-active count.
      2) Break ties with round-robin across chat_id groups.
      3) Within the chosen chat_id, pick its earliest queued task.

    Must be called while queue_lock is held.
    """
    global _rr_last_chat_id

    if not pending_queue:
        return None

    # Ordered first-seen chat_id list from the pending queue.
    chats_in_order = []
    seen = set()
    for item in pending_queue:
        chat = item.get('chat_id')
        if chat not in seen:
            seen.add(chat)
            chats_in_order.append(chat)

    # Find the minimum active count among chat_ids that currently have pending tasks.
    min_active = min(active_by_chat.get(chat, 0) for chat in chats_in_order)
    eligible_chats = [chat for chat in chats_in_order if active_by_chat.get(chat, 0) == min_active]

    # Round-robin tie-break across eligible chats.
    if _rr_last_chat_id in eligible_chats:
        start = eligible_chats.index(_rr_last_chat_id)
        chosen_chat = eligible_chats[(start + 1) % len(eligible_chats)]
    else:
        chosen_chat = eligible_chats[0]

    # Pop the earliest queued task for that chosen chat.
    for idx, item in enumerate(pending_queue):
        if item.get('chat_id') == chosen_chat:
            _rr_last_chat_id = chosen_chat
            return idx

    return None


def _dispatcher() -> None:
    """
    Single lightweight thread that pops tasks from pending_queue and
    submits them to the ThreadPoolExecutor.

    Sleeping 0.5 s when the queue is empty keeps CPU usage negligible
    while still reacting to new tasks within half a second.

    A fresh threading.Event is injected into every task here so that:
      • Retried tasks always start with a clean (unset) stop signal.
      • The event is available to the downloader closures via task['_stop'].
    """
    while not _dispatcher_stop.is_set():
        # Throttle submissions: never feed the executor if all worker slots are busy.
        total_active, active_by_chat = _snapshot_active_by_chat()
        if total_active >= MAX_CONCURRENT_DOWNLOADS:
            _dispatcher_stop.wait(0.5)
            continue

        task = None
        with config.queue_lock:
            if config.pending_queue and not _dispatcher_stop.is_set():
                best_index = _pick_fair_pending_index(config.pending_queue, active_by_chat)
                if best_index is not None:
                    task = config.pending_queue.pop(best_index)

        if task is None:
            _dispatcher_stop.wait(0.5)
            continue

        # Inject a FRESH per-task cancellation event (always overwrite so
        # retried tasks are not pre-cancelled from the previous attempt).
        task['_stop'] = threading.Event()

        with _worker_lock:
            executor = _executor
        if executor is None or _dispatcher_stop.is_set():
            with config.queue_lock:
                config.pending_queue.insert(0, task)
            continue

        try:
            executor.submit(_run_task, task)
        except RuntimeError:
            with config.queue_lock:
                config.pending_queue.insert(0, task)
            if not _dispatcher_stop.is_set():
                logger.exception("Failed to submit queued download task")
                _dispatcher_stop.wait(0.5)


# =============================================================
# Public queue helpers (unchanged API)
# =============================================================
def enqueue(task: dict) -> int:
    with config.queue_lock:
        config.pending_queue.append(task)
        return len(config.pending_queue)


def remove_from_queue(idx: int):
    with config.queue_lock:
        if 0 <= idx < len(config.pending_queue):
            return config.pending_queue.pop(idx)
        return None


def clear_queue() -> None:
    with config.queue_lock:
        config.pending_queue.clear()


def get_queue_items() -> list:
    with config.queue_lock:
        return list(config.pending_queue)


# =============================================================
# Internal: route a task to the correct downloader
# =============================================================
def _dispatch(task: dict) -> None:
    t_type = task['type']
    if t_type == 'youtube':
        from downloaders.youtube import process_youtube_download
        process_youtube_download(task)
    elif t_type == 'youtube_playlist':
        from downloaders.youtube import process_playlist_download
        process_playlist_download(task)
    elif t_type == 'torrent':
        from downloaders.torrent import process_torrent_download
        process_torrent_download(task)
    elif t_type == 'direct':
        from downloaders.direct import process_direct_download
        process_direct_download(task)
    elif t_type == 'social':
        from downloaders.social import ytdlp_universal
        ytdlp_universal(task)
    elif t_type == 'soundcloud_playlist':
        from downloaders.social import process_soundcloud_playlist
        process_soundcloud_playlist(task)
    else:
        cid = task.get('chat_id')
        from locales import t as _t
        raise ValueError(
            _t(cid, 'unknown_task_type', t=t_type) if cid else
            f"نوع task ناشناخته: {t_type}"
        )


# =============================================================
# Start the worker pool and dispatcher
# =============================================================
def start_worker() -> None:
    """
    Create the ThreadPoolExecutor and launch the dispatcher thread.
    MAX_CONCURRENT_DOWNLOADS (env: MAX_CONCURRENT_DOWNLOADS, default 2)
    controls how many downloads can run simultaneously.
    """
    global _executor, _dispatcher_thread
    with _worker_lock:
        if _executor is not None and _dispatcher_thread is not None and _dispatcher_thread.is_alive():
            logger.info("Download pool already running (max_workers=%d)", MAX_CONCURRENT_DOWNLOADS)
            return

        _dispatcher_stop.clear()
        config.stop_event.clear()
        _executor = ThreadPoolExecutor(
            max_workers=MAX_CONCURRENT_DOWNLOADS,
            thread_name_prefix='dl_worker',
        )
        _dispatcher_thread = threading.Thread(
            target=_dispatcher,
            daemon=True,
            name='dl_dispatcher',
        )
        _dispatcher_thread.start()
        logger.info("Download pool started (max_workers=%d)", MAX_CONCURRENT_DOWNLOADS)


def stop_worker(cancel_pending: bool = True) -> None:
    """
    Stop the dispatcher and ask active downloads/uploads to cancel.

    Running downloader functions observe their per-task ``_stop`` event.
    Google Drive uploads also observe ``config.stop_event``.
    """
    global _executor, _dispatcher_thread

    with _worker_lock:
        executor = _executor
        dispatcher = _dispatcher_thread
        _dispatcher_stop.set()
        config.stop_event.set()

        if cancel_pending:
            with config.queue_lock:
                config.pending_queue.clear()

        with config.current_tasks_lock:
            active_tasks = list(config.current_tasks.values())

        for task in active_tasks:
            stop_event = task.get('_stop')
            if stop_event is not None:
                try:
                    stop_event.set()
                except Exception:
                    logger.exception("Could not set task stop event")

        _executor = None
        _dispatcher_thread = None

    if dispatcher is not None and dispatcher.is_alive():
        dispatcher.join(timeout=2)

    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)

    logger.info(
        "Download pool stopped (cancel_pending=%s, active_signalled=%d)",
        cancel_pending,
        len(active_tasks),
    )
