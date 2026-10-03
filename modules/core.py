import os
import re
import time
import shlex
import datetime
import aiohttp
import aiofiles
import asyncio
import logging
import requests
import tgcrypto
import subprocess
import concurrent.futures

from utils import progress_bar

from pyrogram import Client, filters
from pyrogram.types import Message

from pytube import Playlist  #Youtube Playlist Extractor
from yt_dlp import YoutubeDL
import yt_dlp as youtube_dl


# ─────────────────────────────────────────────
#  TITLE SANITIZER  –  handles Hindi, emoji,
#  multiple colons, brackets, ratio signs, etc.
# ─────────────────────────────────────────────
def sanitize_title(title: str) -> str:
    """
    Convert any messy video title into a safe filename string.

    Handles:
      • Hindi / Devanagari and other Unicode text  → kept as-is
      • Multiple colons  (:, ：)                   → replaced with " -"
      • Ratio signs  (∶)                           → replaced with "-"
      • Multiple brackets  ( ) [ ] { }             → spaces around them
      • Slashes, backslashes                        → replaced with "-"
      • Control characters / null bytes            → stripped
      • Leading / trailing whitespace & dots       → stripped
      • Consecutive spaces                         → collapsed to one space
    """
    if not title:
        return "untitled"

    # Replace all colon variants with " -"
    title = re.sub(r'[：:∶]+', ' -', title)

    # Replace slashes and backslashes
    title = re.sub(r'[/\\]+', '-', title)

    # Strip extra risky/decorative symbols entirely
    title = re.sub(r'''[@#${}\[\]%₹'";!?*()=~`&+,]''', '', title)

    # Collapse multiple dashes created above
    title = re.sub(r'-{2,}', '-', title)

    # Replace ratio / pipe / angle brackets that break paths
    title = re.sub(r'[|<>]', '-', title)

    # Strip null bytes and ASCII control characters (keep Unicode)
    title = re.sub(r'[\x00-\x1f\x7f]', '', title)

    # Collapse multiple spaces / tabs
    title = re.sub(r'[ \t]+', ' ', title)

    # Strip leading/trailing whitespace and dots
    title = title.strip(' .')

    return title if title else "untitled"


# ─────────────────────────────────────────────
#  URL EXTRACTOR  –  handles nested / duplicate
#  proxy URLs like:
#    https://proxy.com/pw?url=https://proxy.com/pw?url=https://real.mpd&...
#  → always returns the FIRST (outermost) URL
# ─────────────────────────────────────────────
def extract_first_url(raw: str) -> str:
    """
    Given a string that may contain one or more URLs (http/https),
    return only the FIRST complete URL found.

    Works for:
      • Plain URLs
      • Nested proxy URLs  (?url=https://...?url=https://...)
      • URLs embedded in text / log lines
    """
    raw = raw.strip()
    # Find the position of the very first http:// or https://
    match = re.search(r'https?://', raw)
    if not match:
        return raw  # no URL found, return as-is

    # Slice from the first http and return (trim trailing whitespace/newlines)
    first_url = raw[match.start():].split()[0]
    return first_url


def duration(filename):
    """
    Return duration in seconds as float.
    Safe against: empty output, error messages, non-UTF8 bytes.
    """
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration", "-of",
         "default=noprint_wrappers=1:nokey=1", filename],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )
    output = result.stdout.decode('utf-8', errors='ignore').strip()
    try:
        return float(output)
    except ValueError:
        # ffprobe returned an error message or empty string → fallback to 0
        logging.warning(f"duration(): could not parse ffprobe output for '{filename}': {output!r}")
        return 0

    
def exec(cmd):
        process = subprocess.run(cmd, stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        output = process.stdout.decode()
        print(output)
        return output
        #err = process.stdout.decode()
def pull_run(work, cmds):
    with concurrent.futures.ThreadPoolExecutor(max_workers=work) as executor:
        print("Waiting for tasks to complete")
        fut = executor.map(exec,cmds)
async def aio(url,name):
    k = f'{name}.pdf'
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                f = await aiofiles.open(k, mode='wb')
                await f.write(await resp.read())
                await f.close()
    return k


async def download(url,name):
    ka = f'{name}.pdf'
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                f = await aiofiles.open(ka, mode='wb')
                await f.write(await resp.read())
                await f.close()
    return ka



def parse_vid_info(info):
    info = info.strip()
    info = info.split("\n")
    new_info = []
    temp = []
    for i in info:
        i = str(i)
        if "[" not in i and '---' not in i:
            while "  " in i:
                i = i.replace("  ", " ")
            i.strip()
            i = i.split("|")[0].split(" ",2)
            try:
                if "RESOLUTION" not in i[2] and i[2] not in temp and "audio" not in i[2]:
                    temp.append(i[2])
                    new_info.append((i[0], i[2]))
            except:
                pass
    return new_info


def vid_info(info):
    info = info.strip()
    info = info.split("\n")
    new_info = dict()
    temp = []
    for i in info:
        i = str(i)
        if "[" not in i and '---' not in i:
            while "  " in i:
                i = i.replace("  ", " ")
            i.strip()
            i = i.split("|")[0].split(" ",3)
            try:
                if "RESOLUTION" not in i[2] and i[2] not in temp and "audio" not in i[2]:
                    temp.append(i[2])
                    
                    # temp.update(f'{i[2]}')
                    # new_info.append((i[2], i[0]))
                    #  mp4,mkv etc ==== f"({i[1]})" 
                    
                    new_info.update({f'{i[2]}':f'{i[0]}'})

            except:
                pass
    return new_info



async def run(cmd):
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)

    stdout, stderr = await proc.communicate()

    print(f'[{cmd!r} exited with {proc.returncode}]')
    if proc.returncode == 1:
        return False
    if stdout:
        return f'[stdout]\n{stdout.decode()}'
    if stderr:
        return f'[stderr]\n{stderr.decode()}'

    

def old_download(url, file_name, chunk_size = 1024 * 10):
    if os.path.exists(file_name):
        os.remove(file_name)
    r = requests.get(url, allow_redirects=True, stream=True)
    with open(file_name, 'wb') as fd:
        for chunk in r.iter_content(chunk_size=chunk_size):
            if chunk:
                fd.write(chunk)
    return file_name


def human_readable_size(size, decimal_places=2):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB', 'PB']:
        if size < 1024.0 or unit == 'PB':
            break
        size /= 1024.0
    return f"{size:.{decimal_places}f} {unit}"


def time_name():
    date = datetime.date.today()
    now = datetime.datetime.now()
    current_time = now.strftime("%H%M%S")
    return f"{date} {current_time}.mp4"

def get_playlist_videos(playlist_url):
    try:
        # Create a Playlist object
        playlist = Playlist(playlist_url)
        
        # Get the playlist title
        playlist_title = playlist.title
        
        # Initialize an empty dictionary to store video names and links
        videos = {}
        
        # Iterate through the videos in the playlist
        for video in playlist.videos:
            try:
                video_title = video.title
                video_url = video.watch_url
                videos[video_title] = video_url
            except Exception as e:
                logging.error(f"Could not retrieve video details: {e}")
        
        return playlist_title, videos
    except Exception as e:
        logging.error(f"An error occurred: {e}")
        return None, None

def get_all_videos(channel_url):
    ydl_opts = {
        'quiet': True,
        'extract_flat': True,
        'skip_download': True
    }

    all_videos = []
    with YoutubeDL(ydl_opts) as ydl:
        result = ydl.extract_info(channel_url, download=False)
        
        if 'entries' in result:
            channel_name = result['title']
            all_videos.extend(result['entries'])
            
            while 'entries' in result and '_next' in result:
                next_page_url = result['_next']
                result = ydl.extract_info(next_page_url, download=False)
                all_videos.extend(result['entries'])
            
            video_links = {index+1: (video['title'], video['url']) for index, video in enumerate(all_videos)}
            return video_links, channel_name
        else:
            return None, None

def save_to_file(video_links, channel_name):
    # Sanitize the channel name to be a valid filename
    sanitized_channel_name = re.sub(r'[^\w\s-]', '', channel_name).strip().replace(' ', '_')
    filename = f"{sanitized_channel_name}.txt"    
    with open(filename, 'w', encoding='utf-8') as file:
        for number, (title, url) in video_links.items():
            # Ensure the URL is formatted correctly
            if url.startswith("https://"):
                formatted_url = url
            elif "shorts" in url:
                formatted_url = f"https://www.youtube.com{url}"
            else:
                formatted_url = f"https://www.youtube.com/watch?v={url}"
            file.write(f"{number}. {title}: {formatted_url}\n")
    return filename

async def download_video(url, cmd, name):
    download_cmd = f'{cmd} -R 25 --fragment-retries 25 --external-downloader aria2c --downloader-args "aria2c: -x 16 -j 32"'
    global failed_counter
    print(download_cmd)
    logging.info(download_cmd)
    k = subprocess.run(download_cmd, shell=True)
    
    # Check if the URL is of type 'visionias' or 'penpencilvod'
    if "visionias" in cmd:
        return await download_visionias(url, cmd, name)
    elif "penpencilvod" in cmd:
        return await download_penpencilvod(url, cmd, name)
    else:
        # Default handling for other types of URLs
        return await default_download(url, cmd, name)

async def download_visionias(url, cmd, name):
    global failed_counter
    # Retry logic for 'visionias' URLs
    if failed_counter <= 10:
        failed_counter += 1
        await asyncio.sleep(5)
        return await download_video(url, cmd, name)
    else:
        # Reset failed_counter if the download succeeds
        failed_counter = 0
        return await default_download(url, cmd, name)

async def download_penpencilvod(url, cmd, name):
    global failed_counter
    # Retry logic for 'penpencilvod' URLs
    if failed_counter <= 10:
        failed_counter += 1
        await asyncio.sleep(5)
        return await download_video(url, cmd, name)
    else:
        # Reset failed_counter if the download succeeds
        failed_counter = 0
        return await default_download(url, cmd, name)

async def download_video(url,cmd, name):
    download_cmd = f'{cmd} -R 25 --fragment-retries 25 --external-downloader aria2c --downloader-args "aria2c: -x 16 -j 32"'
    global failed_counter
    print(download_cmd)
    logging.info(download_cmd)
    k = subprocess.run(download_cmd, shell=True)
    if "visionias" in cmd and k.returncode != 0 and failed_counter <= 10:
        failed_counter += 1
        await asyncio.sleep(5)
        await download_video(url, cmd, name)
    failed_counter = 0
    try:
        if os.path.isfile(name):
            return name
        elif os.path.isfile(f"{name}.webm"):
            return f"{name}.webm"
        name = name.split(".")[0]
        if os.path.isfile(f"{name}.mkv"):
            return f"{name}.mkv"
        elif os.path.isfile(f"{name}.mp4"):
            return f"{name}.mp4"
        elif os.path.isfile(f"{name}.mp4.webm"):
            return f"{name}.mp4.webm"

        return name
    except FileNotFoundError as exc:
        return os.path.isfile.splitext[0] + "." + "mp4"


async def send_doc(bot: Client, m: Message,cc,ka,cc1,prog,count,name):
    reply = await m.reply_text(f"Uploading » `{name}`")
    time.sleep(1)
    start_time = time.time()
    await m.reply_document(ka,caption=cc1)
    count+=1
    await reply.delete (True)
    time.sleep(1)
    os.remove(ka)
    time.sleep(3) 


async def send_vid(bot: Client, m: Message,cc,filename,thumb,name,prog):
    subprocess.run(
        f'ffmpeg -i {shlex.quote(filename)} -ss 00:01:00 -vframes 1 {shlex.quote(filename + ".jpg")}',
        shell=True
    )
    await prog.delete (True)
    reply = await m.reply_text(f"**⥣ ᴜᴘʟᴏᴀᴅɪɴɢ ...🤝** » `{name}`")
    try:
        if thumb == "no":
            thumbnail = f"{filename}.jpg"
        else:
            thumbnail = thumb
    except Exception as e:
        await m.reply_text(str(e))

    dur = int(duration(filename))

    start_time = time.time()

    try:
        await m.reply_video(filename,caption=cc, supports_streaming=True,height=720,width=1280,thumb=thumbnail,duration=dur, progress=progress_bar,progress_args=(reply,start_time))
    except Exception:
        await m.reply_document(filename,caption=cc, progress=progress_bar,progress_args=(reply,start_time))
    os.remove(filename)

    os.remove(f"{filename}.jpg")
    await reply.delete (True)


# ══════════════════════════════════════════════════════════════════════════
#  🚀 HYPER-SPEED ADD-ON  (new code only — nothing above this line changed)
# ══════════════════════════════════════════════════════════════════════════
#  download_video_fast()  -> drop-in, faster replacement for download_video()
#  send_vid_fast()        -> drop-in, faster replacement for send_vid()
#
#  Both are 100% additive: if the new speed-up modules aren't available, or
#  anything inside them fails for any reason, execution transparently falls
#  back to the ORIGINAL, unmodified functions above. The bot's behaviour can
#  never regress because of this section.
# ══════════════════════════════════════════════════════════════════════════
try:
    from fast_download import smart_download_video
    _FAST_DOWNLOAD_AVAILABLE = True
except Exception as _fd_err:
    logging.warning(f"fast_download module unavailable, download speed boost disabled: {_fd_err}")
    _FAST_DOWNLOAD_AVAILABLE = False

try:
    from fast_upload import turbo_send_video
    _FAST_UPLOAD_AVAILABLE = True
except Exception as _fu_err:
    logging.warning(f"fast_upload module unavailable, upload speed boost disabled: {_fu_err}")
    _FAST_UPLOAD_AVAILABLE = False


async def download_video_fast(url, cmd, name, workers: int = 16, chunk_mb: int = 10):
    """
    Faster drop-in replacement for download_video().
    Tries: (1) parallel byte-range download for direct file URLs,
    (2) aria2c multi-connection direct fetch, (3) the existing
    yt-dlp+aria2c pipeline boosted with extra fragment concurrency.
    Always falls back to the original download_video() if anything fails.
    """
    if not _FAST_DOWNLOAD_AVAILABLE:
        return await download_video(url, cmd, name)
    try:
        return await smart_download_video(
            url, cmd, name,
            workers=workers,
            chunk_mb=chunk_mb,
            fallback_download=download_video,
        )
    except Exception as e:
        logging.warning(f"[download_video_fast] hyper-speed path failed ({e}); using original pipeline")
        return await download_video(url, cmd, name)


async def send_vid_fast(bot: Client, m: Message, cc, filename, thumb, name, prog, workers: int = 12):
    """
    Faster drop-in replacement for send_vid().
    Tries a turbo multi-connection parallel upload first; on ANY failure
    (different Pyrogram version/internal API, network hiccup, stalled
    upload, etc.) it transparently falls back to the normal Pyrogram upload.
    """
    # -y / -nostdin: a leftover .jpg from an earlier crashed run can never
    # make ffmpeg stop and wait for a keypress.
    subprocess.run(
        f'ffmpeg -y -nostdin -loglevel error -i {shlex.quote(filename)} -ss 00:01:00 -vframes 1 {shlex.quote(filename + ".jpg")}',
        shell=True
    )
    await prog.delete(True)
    reply = await m.reply_text(f"**⥣ ᴜᴘʟᴏᴀᴅɪɴɢ (turbo) ...🤝** » `{name}`")

    try:
        if thumb == "no":
            thumbnail = f"{filename}.jpg"
        else:
            thumbnail = thumb
    except Exception as e:
        await m.reply_text(str(e))
        thumbnail = f"{filename}.jpg"

    # If the thumbnail file doesn't exist (e.g. video shorter than 1 min and
    # ffmpeg produced no frame), upload without a thumb instead of failing.
    if thumbnail and not os.path.exists(thumbnail):
        thumbnail = None

    dur = int(duration(filename))
    start_time = time.time()

    if _FAST_UPLOAD_AVAILABLE:
        try:
            # Safety net: stall detection lives inside fast_upload (per-part
            # timeouts + retries); this generous overall limit guarantees the
            # bot can NEVER sit on "UPLOADING" forever — worst case it falls
            # through to the normal upload below.
            try:
                _size_mb = os.path.getsize(filename) / (1024 * 1024)
            except OSError:
                _size_mb = 500
            _turbo_limit = max(1200, int(_size_mb * 8))
            await asyncio.wait_for(
                turbo_send_video(
                    bot, m.chat.id, filename, cc, thumbnail, dur, 1280, 720,
                    workers=workers, progress=progress_bar, progress_args=(reply, start_time),
                ),
                timeout=_turbo_limit,
            )
            os.remove(filename)
            if os.path.exists(f"{filename}.jpg"):
                os.remove(f"{filename}.jpg")
            await reply.delete(True)
            return
        except BaseException as e:
            if isinstance(e, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                raise
            logging.warning(f"[send_vid_fast] turbo upload failed, falling back to normal upload: {e!r}")

    # ── Fallback: identical to the original send_vid() upload logic ──
    try:
        await m.reply_video(
            filename, caption=cc, supports_streaming=True, height=720, width=1280,
            thumb=thumbnail, duration=dur, progress=progress_bar, progress_args=(reply, start_time),
        )
    except Exception:
        await m.reply_document(filename, caption=cc, progress=progress_bar, progress_args=(reply, start_time))
    os.remove(filename)
    if os.path.exists(f"{filename}.jpg"):
        os.remove(f"{filename}.jpg")
    await reply.delete(True)
