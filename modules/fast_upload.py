# ══════════════════════════════════════════════════════════════════════════
#  fast_upload.py  —  HYPER-SPEED UPLOAD ADD-ON (safe by design)
# ══════════════════════════════════════════════════════════════════════════
#  Pyrogram's default upload sends one file-part (512KB) at a time and
#  waits for Telegram's reply before sending the next one. This module
#  uploads a file by firing MANY SaveFilePart/SaveBigFilePart requests
#  CONCURRENTLY over a small pool of media sessions, then sends the
#  finished file via a raw messages.SendMedia call.
#
#  ✅ FIX (upload stuck at "UPLOADING (turbo) ...")
#  The old version had three problems that could freeze an upload forever:
#    1. It read the WHOLE video into RAM before sending anything
#       (one asyncio task per 512KB part, created in a tight loop).
#       A 300–500MB lecture = 300–500MB of RAM on Render/Termux -> the
#       process was starved/killed and the message stayed on "UPLOADING".
#    2. Every part went through ONE session with no timeout and no retry,
#       so a single lost reply = a hang that never ends.
#    3. Progress callbacks ran while holding a lock, so a slow message
#       edit could block the whole upload.
#
#  The new version:
#    • Streams the file: only `workers` parts (~6MB) are in memory at once.
#    • Uses a small pool of sessions and round-robins parts across them.
#    • Every part has a timeout + automatic retry (on a different session).
#    • Progress updates are throttled and run in the background — they can
#      never block or break the upload.
#    • Every step has a timeout, so if anything is truly dead it RAISES
#      and core.py falls back to the normal Pyrogram upload instead of
#      hanging forever.
#
#  This touches Pyrogram's raw/session internals, which can vary slightly
#  between Pyrogram versions/forks. EVERY entry point here is meant to be
#  wrapped in try/except by the caller (core.py does this) — if anything
#  fails, the caller falls back to the plain, original m.reply_video() /
#  m.reply_document().
# ══════════════════════════════════════════════════════════════════════════

import os
import math
import time
import asyncio
import logging
from hashlib import md5

try:
    from pyrogram import raw
    from pyrogram.session import Session
    _RAW_OK = True
except Exception as _e:
    _RAW_OK = False
    logging.info(f"[fast_upload] pyrogram raw API not importable, turbo upload disabled: {_e}")

PART_SIZE = 512 * 1024          # Telegram's fixed upload part size

MAX_SESSIONS = 3                # parallel media connections (Pyrogram itself uses up to 4)
MAX_WORKERS = 16                # hard cap on in-flight parts (=> max ~8MB of RAM)
PART_TIMEOUT = 60               # seconds to wait for ONE part's reply
PART_RETRIES = 4                # attempts per part before giving up (-> fallback upload)
SESSION_START_TIMEOUT = 30      # seconds to wait for media sessions to connect
SESSION_STOP_TIMEOUT = 10
THUMB_TIMEOUT = 60
SEND_MEDIA_TIMEOUT = 180        # final SendMedia call
PROGRESS_INTERVAL = 3.0         # min seconds between progress callbacks
PROGRESS_TIMEOUT = 15

log = logging.getLogger(__name__)


async def _stop_sessions(sessions):
    for s in sessions:
        try:
            await asyncio.wait_for(s.stop(), SESSION_STOP_TIMEOUT)
        except BaseException as e:           # noqa: BLE001 - cleanup must never raise
            if isinstance(e, asyncio.CancelledError):
                raise
            log.debug(f"[fast_upload] session stop ignored: {e!r}")


async def fast_upload(client, path: str, workers: int = 12, progress=None, progress_args=()):
    """
    Uploads `path` using many concurrent part-upload RPCs instead of
    Pyrogram's default sequential one-part-at-a-time loop.
    Returns a raw InputFile/InputFileBig ready for InputMediaUploadedDocument.
    Raises on any problem so the caller can fall back safely.
    """
    if not _RAW_OK:
        raise RuntimeError("pyrogram raw API unavailable")

    file_size = os.path.getsize(path)
    if file_size <= 0:
        raise RuntimeError("empty file, nothing to upload")

    workers = max(1, min(int(workers or 1), MAX_WORKERS))
    is_big = file_size > 10 * 1024 * 1024
    file_total_parts = math.ceil(file_size / PART_SIZE)
    file_id = client.rnd_id()

    dc_id = await client.storage.dc_id()
    auth_key = await client.storage.auth_key()
    test_mode = await client.storage.test_mode()

    n_sessions = max(1, min(MAX_SESSIONS, workers))
    sessions = [Session(client, dc_id, auth_key, test_mode, is_media=True) for _ in range(n_sessions)]

    state = {"uploaded": 0, "last_prog": 0.0, "prog_busy": False}
    errors = []
    failed = asyncio.Event()
    sem = asyncio.Semaphore(workers)
    md5_sum = md5() if not is_big else None
    bg_tasks = set()          # keeps background progress tasks alive

    def _fire_progress():
        if progress is None or state["prog_busy"]:
            return
        now = time.monotonic()
        if now - state["last_prog"] < PROGRESS_INTERVAL:
            return
        state["prog_busy"] = True
        state["last_prog"] = now
        current = state["uploaded"]

        async def _run():
            try:
                await asyncio.wait_for(progress(current, file_size, *progress_args), PROGRESS_TIMEOUT)
            except Exception:
                pass            # progress is cosmetic — never let it affect the upload
            finally:
                state["prog_busy"] = False

        t = asyncio.create_task(_run())
        bg_tasks.add(t)
        t.add_done_callback(bg_tasks.discard)

    async def push_part(index, data):
        last_err = None
        for attempt in range(PART_RETRIES):
            session = sessions[(index + attempt) % len(sessions)]
            try:
                if is_big:
                    rpc = raw.functions.upload.SaveBigFilePart(
                        file_id=file_id, file_part=index,
                        file_total_parts=file_total_parts, bytes=data,
                    )
                else:
                    rpc = raw.functions.upload.SaveFilePart(
                        file_id=file_id, file_part=index, bytes=data,
                    )
                ok = await asyncio.wait_for(session.invoke(rpc), PART_TIMEOUT)
                if ok:
                    return
                last_err = RuntimeError(f"Telegram rejected part {index}")
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError:
                last_err = TimeoutError(f"part {index} timed out after {PART_TIMEOUT}s (attempt {attempt + 1})")
            except Exception as e:                      # noqa: BLE001
                last_err = e
            if attempt < PART_RETRIES - 1:
                await asyncio.sleep(min(2 ** attempt, 8))
        raise last_err or RuntimeError(f"part {index} failed")

    async def runner(index, data):
        try:
            await push_part(index, data)
            state["uploaded"] += len(data)
            _fire_progress()
        except asyncio.CancelledError:
            raise
        except Exception as e:                          # noqa: BLE001
            errors.append(e)
            failed.set()
        finally:
            sem.release()

    live = set()
    try:
        # connect the media sessions (with timeout so we can never hang here)
        await asyncio.wait_for(
            asyncio.gather(*(s.start() for s in sessions)),
            SESSION_START_TIMEOUT,
        )

        loop = asyncio.get_running_loop()
        with open(path, "rb") as f:
            idx = 0
            while not failed.is_set():
                data = await loop.run_in_executor(None, f.read, PART_SIZE)
                if not data:
                    break
                # wait for a free slot BEFORE queuing -> RAM stays bounded
                await sem.acquire()
                if failed.is_set():
                    sem.release()
                    break
                if md5_sum is not None:
                    md5_sum.update(data)   # sequential read order -> checksum stays correct
                t = asyncio.create_task(runner(idx, data))
                live.add(t)
                t.add_done_callback(live.discard)
                idx += 1

        if live:
            await asyncio.gather(*list(live))
        if errors:
            raise errors[0]
        if state["uploaded"] < file_size:
            raise RuntimeError(f"incomplete upload: {state['uploaded']}/{file_size} bytes")
    finally:
        for t in list(live):
            t.cancel()
        if live:
            await asyncio.gather(*list(live), return_exceptions=True)
        for t in list(bg_tasks):
            t.cancel()
        await _stop_sessions(sessions)

    name = os.path.basename(path)
    if is_big:
        return raw.types.InputFileBig(id=file_id, parts=file_total_parts, name=name)
    return raw.types.InputFile(
        id=file_id, parts=file_total_parts, name=name,
        md5_checksum=md5_sum.hexdigest() if md5_sum else "",
    )


async def turbo_send_video(
    client, chat_id, filepath, caption, thumb_path,
    duration, width=1280, height=720,
    workers: int = 12, progress=None, progress_args=(),
):
    """
    Full turbo replacement for client.send_video():
    fast_upload() for the big file + normal save_file() for the (tiny)
    thumbnail + a manual raw messages.SendMedia call. Raises on any
    problem so the caller can fall back to the original send_vid().
    """
    if not _RAW_OK:
        raise RuntimeError("pyrogram raw API unavailable")

    peer = await asyncio.wait_for(client.resolve_peer(chat_id), 30)

    thumb_input = None
    if thumb_path and os.path.exists(thumb_path):
        try:
            # small file, normal path is fine
            thumb_input = await asyncio.wait_for(client.save_file(thumb_path), THUMB_TIMEOUT)
        except Exception:
            thumb_input = None

    big_input = await fast_upload(
        client, filepath, workers=workers, progress=progress, progress_args=progress_args,
    )

    parsed = await client.parser.parse(caption or "")
    message_text = parsed["message"]
    entities = parsed["entities"]

    attributes = [
        raw.types.DocumentAttributeVideo(
            supports_streaming=True,
            duration=int(duration or 0),
            w=int(width or 1280),
            h=int(height or 720),
        ),
        raw.types.DocumentAttributeFilename(file_name=os.path.basename(filepath)),
    ]

    media = raw.types.InputMediaUploadedDocument(
        file=big_input,
        thumb=thumb_input,
        mime_type="video/mp4",
        attributes=attributes,
    )

    return await asyncio.wait_for(
        client.invoke(
            raw.functions.messages.SendMedia(
                peer=peer,
                media=media,
                message=message_text,
                random_id=client.rnd_id(),
                entities=entities,
            )
        ),
        SEND_MEDIA_TIMEOUT,
    )
