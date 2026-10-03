import os
import re
import sys
import json
import time
import asyncio
import random
import requests
import subprocess
import urllib.parse
import yt_dlp
import cloudscraper
import m3u8
import io
import core as helper
from utils import progress_bar
from PIL import Image
from vars import API_ID, API_HASH, BOT_TOKEN, OWNER, AUTH_USERS as VARS_AUTH_USERS
from aiohttp import ClientSession
from pyromod import listen
from subprocess import getstatusoutput
from pytube import YouTube
from aiohttp import web

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait
from pyrogram.errors.exceptions.bad_request_400 import StickerEmojiInvalid
from pyrogram.types.messages_and_media import message
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# ── Owner ID (update this with your actual owner Telegram ID) ────────────────
OWNER = int(os.environ.get("OWNER", "8715662594"))
# ─────────────────────────────────────────────────────────────────────────────

# ── Live-changeable PW API endpoints (/changeapi command updates both) ───────
API_FILE = "pw_api.json"

def _load_api():
    try:
        with open(API_FILE, "r") as f:
            data = json.load(f)
            return data.get("PWAPI1"), data.get("PWAPI2")
    except Exception:
        return None, None

def _save_api(api1: str, api2: str):
    try:
        with open(API_FILE, "w") as f:
            json.dump({"PWAPI1": api1, "PWAPI2": api2}, f)
    except Exception:
        pass

_saved_api1, _saved_api2 = _load_api()
_default_api = "https://ankitshakyaxapi.vercel.app/download?mpd_url"
PWAPI1 = _saved_api1 or os.environ.get("PWAPI1", _default_api)
PWAPI2 = _saved_api2 or os.environ.get("PWAPI2", _default_api)
# ─────────────────────────────────────────────────────────────────────────────

# ── Persistent Auth Users (JSON-backed, survives bot restart) ────────────────
AUTH_FILE = "auth_users.json"

def _load_auth_users():
    try:
        with open(AUTH_FILE, "r") as f:
            return set(json.load(f))
    except Exception:
        return set()

def _save_auth_users(users: set):
    try:
        with open(AUTH_FILE, "w") as f:
            json.dump(list(users), f)
    except Exception:
        pass

auth_users: set = _load_auth_users()
# ── Also include AUTH_USERS from vars.py (env variable, comma-separated) ─────
auth_users.update(VARS_AUTH_USERS)
# ─────────────────────────────────────────────────────────────────────────────

# ── Persistent Broadcast Users (JSON-backed, survives bot restart) ───────────
BROADCAST_FILE = "broadcast_users.json"

def _load_broadcast_users():
    try:
        with open(BROADCAST_FILE, "r") as f:
            return set(json.load(f))
    except Exception:
        return set()

def _save_broadcast_users(users: set):
    try:
        with open(BROADCAST_FILE, "w") as f:
            json.dump(list(users), f)
    except Exception:
        pass

broadcast_users: set = _load_broadcast_users()
# ─────────────────────────────────────────────────────────────────────────────

# ── Random image list ────────────────────────────────────────────────────────
image_list = [
    "https://graph.org/file/f417c8938b2084078b8e7-3e7a30e4c17a9a1ac2.jpg",
    "https://graph.org/file/67b43ca11ff3ae7f3bd4e-bc78bedf9e58efc35a.jpg",
    "https://graph.org/file/96f7e50b37c6bd4dc5071-5eadeaf54110b8c34a.jpg",
    "https://graph.org/file/7c9a3a55d7c9a1d85510c-7bdd889d63d9e56123.jpg",
    "https://graph.org/file/e2da63735f5a0c0110538-2001962c850d6624c4.jpg",
    "https://graph.org/file/7452a3a885ec515ab6699-9c485bc63d1ee591e4.jpg",
    "https://graph.org/file/1d1dab8f4dc33df10e38c-a3c92d386be28422ac.jpg",
    "https://graph.org/file/a1c4b27984bb61183048c-d11e4d6c9ea09fcedb.jpg",
    "https://graph.org/file/1d1548631e6d1d3b3796e-b6647f0434c20f100a.jpg",
    "https://graph.org/file/9db3816e75336ecc45959-6d49ddd4d0e92f1aae.jpg",
]
# ─────────────────────────────────────────────────────────────────────────────

# ══════════════════════════════════════════════════════════════════════════════
# ── PDF THUMBNAIL SYSTEM (Pillow-based, Telegram-compliant) ──────────────────
# ══════════════════════════════════════════════════════════════════════════════
# Telegram thumbnail requirements:
#   - Must be a valid JPEG (baseline, not progressive)
#   - Must be < 200 KB
#   - Width & height must NOT exceed 320px
#
# Persistent thumbnail URL is stored in thumb_config.json so it survives
# bot restarts and redeploys. Default URL is hardcoded as fallback.

THUMB_CONFIG_FILE = "thumb_config.json"
DEFAULT_THUMB_URL = " "
DEFAULT_THUMB_URL = " "
THUMB_PATH = "pdf_thumb_v2.jpg"
THUMB_MAX_SIDE = 320
THUMB_MAX_BYTES = 200 * 1024


def _load_thumb_url() -> str:
    """Load saved thumbnail URL from JSON file; fallback to default."""
    try:
        with open(THUMB_CONFIG_FILE, "r") as f:
            data = json.load(f)
            return data.get("thumb_url") or DEFAULT_THUMB_URL
    except Exception:
        return DEFAULT_THUMB_URL


def _save_thumb_url(url: str):
    """Persist thumbnail URL to JSON file."""
    try:
        with open(THUMB_CONFIG_FILE, "w") as f:
            json.dump({"thumb_url": url}, f)
    except Exception:
        pass


def _delete_thumb_url():
    """Remove custom thumbnail URL (revert to default)."""
    try:
        with open(THUMB_CONFIG_FILE, "w") as f:
            json.dump({"thumb_url": None}, f)
    except Exception:
        pass


# In-memory cache of current thumb URL (loaded at startup)
_current_thumb_url: str = _load_thumb_url()


def _process_thumbnail_bytes(raw_bytes: bytes, dest_path: str) -> bool:
    """Save raw image bytes as a Telegram-compliant thumbnail.

    Always force-re-encodes through Pillow as baseline JPEG to avoid
    Telegram silently dropping progressive/ICC-profile images.
    """
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        img.load()
        if img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        scale = min(THUMB_MAX_SIDE / w, THUMB_MAX_SIDE / h, 1.0)
        if scale < 1.0:
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
        quality = 95
        buf = io.BytesIO()
        while quality >= 35:
            buf.seek(0); buf.truncate(0)
            img.save(buf, format="JPEG", quality=quality, optimize=True, progressive=False)
            if buf.tell() < THUMB_MAX_BYTES:
                break
            quality -= 10
        with open(dest_path, "wb") as f:
            f.write(buf.getvalue())
        return True
    except Exception as e:
        print(f"[Thumbnail] Processing failed: {e}")
        return False


def ensure_thumbnail_exists(url: str = None, force: bool = False) -> str | None:
    """Download & process thumbnail from given URL (or current saved URL).
    Returns path to compliant JPEG or None on failure.
    """
    global _current_thumb_url
    thumb_url = url or _current_thumb_url or DEFAULT_THUMB_URL

    if os.path.exists(THUMB_PATH) and not force:
        try:
            with Image.open(THUMB_PATH) as im:
                w, h = im.size
            size_ok = os.path.getsize(THUMB_PATH) < THUMB_MAX_BYTES
            dim_ok = w <= THUMB_MAX_SIDE and h <= THUMB_MAX_SIDE
            if size_ok and dim_ok:
                return THUMB_PATH
        except Exception:
            pass  # fall through and regenerate

    for attempt in range(1, 4):
        try:
            resp = requests.get(thumb_url, timeout=15)
            if resp.status_code == 200 and resp.content:
                if _process_thumbnail_bytes(resp.content, THUMB_PATH):
                    return THUMB_PATH
        except Exception as e:
            print(f"[Thumbnail] Download attempt {attempt} failed: {e}")
        time.sleep(1)
    return None


def get_thumbnail() -> str | None:
    """Return path to Telegram-compliant thumbnail, self-healing if missing."""
    global THUMB_PATH
    if not os.path.exists(THUMB_PATH):
        return ensure_thumbnail_exists(force=True)
    return THUMB_PATH


# Pre-load thumbnail at startup
_THUMBNAIL_FILE = ensure_thumbnail_exists()
# ── End Thumbnail System ──────────────────────────────────────────────────────

# ── Failed/Skipped download notice ───────────────────────────────────────────
async def send_failed_notice(bot, chat_id, vid_id, title, url, reason, hide=()):
    """Send a formatted failed-download notice message.

    `url` should be the ORIGINAL url from the user's txt file.
    `hide` = private strings (e.g. the PW API base url / the edited api url)
    that must never reach the user; they are scrubbed out of `reason`.
    """
    reason = str(reason)
    for _h in hide:
        if _h:
            reason = reason.replace(str(_h), "")
    reason = reason.replace("`", "'").strip()
    if len(reason) > 300:
        reason = reason[:300] + "..."
    if not reason:
        reason = "Unknown error"
    msg = (
        "**🥺ꜱᴏʀʀʏ ɪ ᴄᴀɴ'ᴛ ᴀʙʟᴇ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ ᴛʜɪꜱ:**\n\n"
        + "**🪩ᴠɪᴅ_ɪᴅ:** `" + str(vid_id).zfill(3) + "`\n\n"
        + "**📝 ᴛɪᴛᴇʟ:** " + str(title) + "\n\n"
        + "**ᴜʀʟ:** " + str(url) + "\n\n"
        + "**ʀᴇᴀꜱᴏɴ:** `" + str(reason) + "`\n\n"
        + "**ɪꜰ ʏᴏᴜ ᴛʜɪɴᴋ ɪᴛ ꜱʜᴏᴜʟᴅ ʙᴇ ᴅᴏᴡɴʟᴏᴀᴅᴇᴅ, ᴛʜᴇɴ ᴄᴏɴᴛᴀᴄᴛ ᴛʜᴇ ᴏᴡɴᴇʀ.**"
    )
    try:
        await bot.send_message(
            chat_id,
            msg,
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(text="👑ᴏᴡɴᴇʀ", url="https://t.me/SmartBoy_ApnaMS")]
            ])
        )
    except Exception as e:
        print(f"send_failed_notice error: {e}")
# ─────────────────────────────────────────────────────────────────────────────

# Initialize the bot
bot = Client(
    "bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

my_name = "💜"

cookies_file_path = os.getenv("COOKIES_FILE_PATH", "/modules/youtube_cookies.txt")

# Define aiohttp routes
routes = web.RouteTableDef()

@routes.get("/", allow_head=True)
async def root_route_handler(request):
    return web.json_response("https://text-leech-bot-for-render.onrender.com/")

async def web_server():
    web_app = web.Application(client_max_size=30000000)
    web_app.add_routes(routes)
    return web_app

async def start_bot():
    await bot.start()
    print("ʙᴏᴛ ɪꜱ ᴜᴘ ᴀɴᴅ ʀᴜɴɴɪɴɢ")

async def stop_bot():
    await bot.stop()

async def main():
    if WEBHOOK:
        # Start the web server
        app_runner = web.AppRunner(await web_server())
        await app_runner.setup()
        site = web.TCPSite(app_runner, "0.0.0.0", PORT)
        await site.start()
        print(f"ᴡᴇʙ ꜱᴇʀᴠᴇʀ ꜱᴛᴀʀᴛᴇᴅ ᴏɴ ᴘᴏʀᴛ {PORT}")

    # Start the bot
    await start_bot()

    # Keep the program running
    try:
        while True:
            await bot.polling()  # Run forever, or until interrupted
    except (KeyboardInterrupt, SystemExit):
        await stop_bot()
    

async def start_bot():
    await bot.start()
    print("ʙᴏᴛ ɪꜱ ᴜᴘ ᴀɴᴅ ʀᴜɴɴɪɴɢ")

async def stop_bot():
    await bot.stop()

async def main():
    if WEBHOOK:
        # Start the web server
        app_runner = web.AppRunner(await web_server())
        await app_runner.setup()
        site = web.TCPSite(app_runner, "0.0.0.0", PORT)
        await site.start()
        print(f"ᴡᴇʙ ꜱᴇʀᴠᴇʀ ꜱᴛᴀʀᴛᴇᴅ ᴏɴ ᴘᴏʀᴛ {PORT}")

    # Start the bot
    await start_bot()

    # Keep the program running
    try:
        while True:
            await asyncio.sleep(3600)  # Run forever, or until interrupted
    except (KeyboardInterrupt, SystemExit):
        await stop_bot()
        
class Data:
    START = (
        "🌟 ᴡᴇʟᴄᴏᴍᴇ ʜᴀʙɪʙɪ😋 {0}! 🌟\n\n"
    )
# Define the start command handler
@bot.on_message(filters.command("start"))
async def start(client: Client, msg: Message):
    user = await client.get_me()
    mention = user.mention
    start_message = await client.send_message(
        msg.chat.id,
        Data.START.format(msg.from_user.mention)
    )

    await asyncio.sleep(1)
    await start_message.edit_text(
        Data.START.format(msg.from_user.mention) +
        "ɪɴɪᴛɪᴀʟɪᴢɪɴɢ ᴜᴘʟᴏᴀᴅᴇʀ ʙᴏᴛ... 🤖\n\n"
        "ᴘʀᴏɢʀᴇꜱꜱ: [⬜⬜⬜⬜⬜⬜⬜⬜⬜] 0%\n\n"
    )

    await asyncio.sleep(1)
    await start_message.edit_text(
        Data.START.format(msg.from_user.mention) +
        "ʟᴏᴀᴅɪɴɢ ꜰᴇᴀᴛᴜʀᴇꜱ... ⏳\n\n"
        "ᴘʀᴏɢʀᴇꜱꜱ: [🟥🟥🟥⬜⬜⬜⬜⬜⬜] 25%\n\n"
    )
    
    await asyncio.sleep(1)
    await start_message.edit_text(
        Data.START.format(msg.from_user.mention) +
        "ᴛʜɪꜱ ᴍᴀʏ ᴛᴀᴋᴇ ᴀ ᴍᴏᴍᴇɴᴛ, ꜱɪᴛ ʙᴀᴄᴋ ᴀɴᴅ ʀᴇʟᴀx! 🥵\n\n"
        "ᴘʀᴏɢʀᴇꜱꜱ: [🟧🟧🟧🟧🟧⬜⬜⬜⬜] 50%\n\n"
    )

    await asyncio.sleep(1)
    await start_message.edit_text(
        Data.START.format(msg.from_user.mention) +
        "ᴄʜᴇᴄᴋɪɴɢ ʙᴏᴛ ꜱᴛᴀᴛᴜꜱ... 🔍\n\n"
        "ᴘʀᴏɢʀᴇꜱꜱ: [🟨🟨🟨🟨🟨🟨🟨⬜⬜] 75%\n\n"
    )

    await asyncio.sleep(1)
    await start_message.edit_text(
        Data.START.format(msg.from_user.mention) +
        "ʙᴏᴛ ꜱᴛᴀʀᴛᴇᴅ ʜᴀʙɪʙɪ... ᴄᴏᴍᴍᴀɴᴅ ɪꜱ ᴘʀɪᴠᴀᴛᴇ ᴅᴇᴀʀ😜.**ʙᴏᴛ ᴍᴀᴅᴇ ʙʏ @SmartBoy_ApnaMS**🔍\n\n"
        "ᴘʀᴏɢʀᴇꜱꜱ:[🟩🟩🟩🟩🟩🟩🟩🟩🟩] 100%\n\n"
    )

    # ── Register user for broadcast ───────────────────────────────────────────
    broadcast_users.add(msg.chat.id)
    _save_broadcast_users(broadcast_users)
    # ─────────────────────────────────────────────────────────────────────────

    # ── Send random welcome image ─────────────────────────────────────────────
    await start_message.delete()
    try:
        if msg.chat.id in auth_users:
            caption = (
                f"⬩➤**⚡ʜᴇʟʟᴏ ʜᴀʙɪʙɪ!**\n\n"
                f"⬩➤**ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ᴛʜᴇ ᴅᴏᴡɴʟᴏᴀᴅᴇʀ ꜱᴇʀᴠɪᴄᴇ!**\n\n"
                f"⬩➤**ɪ'ᴍ ʀɪᴄʜ ᴜᴘʟᴏᴀᴅᴇʀ ʙᴏᴛ**\n\n"
                f"⬩➤**ɪ ᴄᴀɴ ᴅᴏᴡɴʟᴏᴀᴅ ᴠɪᴅᴇᴏꜱ & ᴘᴅꜰꜱ ꜰʀᴏᴍ ʏᴏᴜʀ ᴛᴇxᴛ ꜰɪʟᴇ ᴀɴᴅ ꜱᴇɴᴅ ᴛʜᴇᴍ ᴛᴏ ʏᴏᴜ.**\n\n"
                f"⬩➤**ʟᴇᴛ'ꜱ ꜱᴛᴀʀᴛꜱ, ꜱᴇɴᴅ /Habibi ᴄᴏᴍᴍᴀɴᴅ ᴛᴏ ᴍᴇ ʜᴜʀʀʏ📖.**\n\n"
                f"⬩➤**ᴜꜱᴇ /Thumbnail ᴄᴏᴍᴍᴀɴᴅ ᴛᴏ ꜱᴇᴛ ᴛʜᴜᴍʙɴᴀɪʟ ᴏɴ ᴘᴅꜰꜱ😍.**\n\n"
                f"⬩➤**ʙᴏᴛ ᴍᴀᴅᴇ ʙʏ : @SmartBoy_ApnaMS 🗿**."
            )
        else:
            caption = (
                f"⬩➤**🚀ʜᴇʟʟᴏ** {msg.from_user.first_name} **ᴡᴇʟᴄᴏᴍᴇ ʜᴀʙɪʙɪ !**\n\n"
                f"⬩➤**ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ᴛʜᴇ ᴅᴏᴡɴʟᴏᴀᴅᴇʀ ꜱᴇʀᴠɪᴄᴇ!**\n\n"
                f"⬩➤**ɪ'ᴍ ʀɪᴄʜ ᴜᴘʟᴏᴀᴅᴇʀ ʙᴏᴛ\n\n"
                f"⬩➤**ɪ ᴄᴀɴ ᴅᴏᴡɴʟᴏᴀᴅ ᴠɪᴅᴇᴏꜱ & ᴘᴅꜰꜱ ꜰʀᴏᴍ ʏᴏᴜʀ ᴛᴇxᴛ ꜰɪʟᴇ ᴀɴᴅ ꜱᴇɴᴅ ᴛʜᴇᴍ ᴛᴏ ʏᴏᴜ!**\n\n"
                f"⬩➤**🆓 ʏᴏᴜ ᴀʀᴇ ᴄᴜʀʀᴇɴᴛʟʏ ᴜꜱɪɴɢ ᴀ 𝗳𝗿𝗲𝗲 ᴠᴇʀꜱɪᴏɴ!**\n"
                f"⬩➤**ᴡᴀɴɴᴀ ᴀ ᴘʀᴇᴍɪᴜᴍ? ᴄᴏɴᴛᴀᴄᴛ:** @SmartBoy_ApnaMS 💎\n"
            )
        await client.send_photo(chat_id=msg.chat.id, photo=random.choice(image_list), caption=caption)
    except Exception:
        pass
    # ─────────────────────────────────────────────────────────────────────────

@bot.on_message(filters.command(["stop"]) )
async def restart_handler(_, m):
    await m.reply_text("🔴**ꜱᴛᴏᴘᴘᴇᴅ**🔴", True)
    os.execl(sys.executable, sys.executable, *sys.argv)

# ══════════════════════════════════════════════════════════════════════════════
# ── AUTH SYSTEM (Owner only — JSON-backed, survives restarts) ────────────────
# ══════════════════════════════════════════════════════════════════════════════

@bot.on_message(filters.command(["addauth"]))
async def addauth_handler(client: Client, m: Message):
    if m.from_user.id != OWNER:
        return await m.reply_text("❌ ᴏɴʟʏ ᴏᴡɴᴇʀ ᴄᴀɴ ᴜꜱᴇ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ.")
    parts = m.text.split()
    if len(parts) < 2:
        return await m.reply_text("ᴜꜱᴀɢᴇ: /addauth <ᴜꜱᴇʀ_ɪᴅ>")
    try:
        uid = int(parts[1])
    except ValueError:
        return await m.reply_text("❌ ɪɴᴠᴀʟɪᴅ ᴜꜱᴇʀ ɪᴅ.")
    auth_users.add(uid)
    _save_auth_users(auth_users)
    await m.reply_text(f"✅ ᴜꜱᴇʀ `{uid}` ᴀᴅᴅᴇᴅ ᴛᴏ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ʟɪꜱᴛ.\n🥳ɴᴏᴡ ᴛʜɪꜱ ᴜꜱᴇʀ ᴄᴀɴ ᴜꜱᴇ ᴛʜɪꜱ ʙᴏᴛ.")

@bot.on_message(filters.command(["rmauth"]))
async def rmauth_handler(client: Client, m: Message):
    if m.from_user.id != OWNER:
        return await m.reply_text("❌ ᴏɴʟʏ ᴏᴡɴᴇʀ ᴄᴀɴ ᴜꜱᴇ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ.")
    parts = m.text.split()
    if len(parts) < 2:
        return await m.reply_text("ᴜꜱᴀɢᴇ: /rmauth <ᴜꜱᴇʀ_ɪᴅ>")
    try:
        uid = int(parts[1])
    except ValueError:
        return await m.reply_text("❌ ɪɴᴠᴀʟɪᴅ ᴜꜱᴇʀ ɪᴅ.")
    auth_users.discard(uid)
    _save_auth_users(auth_users)
    await m.reply_text(f"✅ ᴜꜱᴇʀ `{uid}` ʀᴇᴍᴏᴠᴇᴅ ꜰʀᴏᴍ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ʟɪꜱᴛ.\n🤫ᴀʟʀɪɢʜᴛꜱ ɴᴏᴡ ᴛʜɪꜱ ᴜꜱᴇʀ ᴄᴀɴ'ᴛ ᴜꜱᴇ ᴛʜɪꜱ ʙᴏᴛ.")

@bot.on_message(filters.command(["users"]))
async def allusers_handler(client: Client, m: Message):
    if m.from_user.id != OWNER:
        return await m.reply_text("❌ ᴏɴʟʏ ᴏᴡɴᴇʀ ᴄᴀɴ ᴜꜱᴇ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ.")
    if not auth_users:
        return await m.reply_text("📋 ɴᴏ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴜꜱᴇʀꜱ ʏᴇᴛ.")
    user_list = "\n".join([f"• `{uid}`" for uid in auth_users])
    await m.reply_text(f"👥 **ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴜꜱᴇʀꜱ ({len(auth_users)}):**\n\n{user_list}")

# ══════════════════════════════════════════════════════════════════════════════
# ── BROADCAST SYSTEM (Owner only — JSON-backed) ───────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

@bot.on_message(filters.command(["broadcast"]))
async def broadcast_handler(client: Client, m: Message):
    if m.from_user.id != OWNER:
        return await m.reply_text("❌ ᴏɴʟʏ ᴏᴡɴᴇʀ ᴄᴀɴ ᴜꜱᴇ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ.")
    if not m.reply_to_message:
        return await m.reply_text("📢 ʀᴇᴘʟʏ ᴛᴏ ᴀ ᴍᴇꜱꜱᴀɢᴇ ᴛᴏ ʙʀᴏᴀᴅᴄᴀꜱᴛ ɪᴛ.")
    
    total = len(broadcast_users)
    if total == 0:
        return await m.reply_text("ɴᴏ ᴜꜱᴇʀꜱ ᴛᴏ ʙʀᴏᴀᴅᴄᴀꜱᴛ ᴛᴏ ʏᴇᴛ.")
    
    status = await m.reply_text(f"📢 ʙʀᴏᴀᴅᴄᴀꜱᴛɪɴɢ ᴛᴏ {total} ᴜꜱᴇʀ...")
    success, failed = 0, 0
    for uid in list(broadcast_users):
        try:
            await m.reply_to_message.copy(uid)
            success += 1
            await asyncio.sleep(0.05)  # flood prevention
        except Exception:
            failed += 1
    await status.edit_text(
        f"📢 **ʙʀᴏᴀᴅᴄᴀꜱᴛ ᴄᴏᴍᴘʟᴇᴛᴇ!**\n\n"
        f"✅ ꜱᴜᴄᴄᴇꜱꜱ: {success}\n"
        f"❌ ꜰᴀɪʟᴇᴅ: {failed}\n"
        f"👥 ᴛᴏᴛᴀʟ: {total}"
    )

@bot.on_message(filters.command(["broadusers"]))
async def broadusers_handler(client: Client, m: Message):
    if m.from_user.id != OWNER:
        return await m.reply_text("❌ ᴏɴʟʏ ᴏᴡɴᴇʀ ᴄᴀɴ ᴜꜱᴇ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ.")
    total = len(broadcast_users)
    if total == 0:
        return await m.reply_text("📋ɴᴏ ʙʀᴏᴀᴅᴄᴀꜱᴛ ᴜꜱᴇʀꜱ ʀᴇɢɪꜱᴛᴇʀᴇᴅ ʏᴇᴛ.")
    uid_list = "\n".join([f"• `{uid}`" for uid in list(broadcast_users)[:50]])
    suffix = f"\n\n...and {total - 50} more." if total > 50 else ""
    await m.reply_text(f"👥 **ʙʀᴏᴀᴅᴄᴀꜱᴛ ᴜꜱᴇʀꜱ ({total}):**\n\n{uid_list}{suffix}")

# ══════════════════════════════════════════════════════════════════════════════
# ── /changeapi COMMAND (Owner only — updates PWAPI1 & PWAPI2 live) ────────────
# ══════════════════════════════════════════════════════════════════════════════

@bot.on_message(filters.command(["changeapi"]))
async def changeapi_handler(client: Client, m: Message):
    global PWAPI1, PWAPI2
    if m.from_user.id != OWNER:
        return await m.reply_text(
            "ᴛᴏ ᴄʜᴀɴɢᴇ ᴏᴜʀ ᴀᴘɪ ɪɴ ᴏᴜʀ ʀᴇᴘᴏꜱɪᴛᴏʀʏ ɪɴ ᴛʜɪꜱ ꜰᴏʀᴍᴀᴛ👇🏻.\n\n"
            "/changeapi ɴᴇᴡ ᴀᴘɪ ʜᴇʀᴇ\n**https... to .com/pw** ᴜᴘᴛᴏ ᴛʜɪꜱ ᴘᴏɪɴᴛ ᴏɴʟʏ😁.\n\n"
            "ʙᴜᴛ ʙᴜᴛ ʜᴀʙɪʙɪ🫡\n"
            "ꜱᴏʀʀʏ ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴍʏ ᴏᴡɴᴇʀ😒."
        )
    parts = m.text.split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        return await m.reply_text(
            "ᴡᴇʟᴄᴏᴍᴇ ʙᴏꜱꜱ! ᴛᴏ ᴄʜᴀɴɢᴇ ᴏᴜʀ ᴀᴘɪ ɪɴ ᴏᴜʀ ʀᴇᴘᴏꜱɪᴛᴏʀʏ ɪɴ ᴛʜɪꜱ ꜰᴏʀᴍᴀᴛ:\n\n"
            "/changeapi ɴᴇᴡ ᴀᴘɪ ʜᴇʀᴇ\n**https... to .com/pw** ᴜᴘᴛᴏ ᴛʜɪꜱ ᴘᴏɪɴᴛ ᴏɴʟʏ😁.\n\n"
            "ꜱᴇɴᴅ ᴍᴇ ʙᴏꜱꜱ ɪ ᴡɪʟʟ ᴄʜᴀɴɢᴇ ɪᴛ.✨"
        )
    new_api = parts[1].strip()
    PWAPI1 = new_api
    PWAPI2 = new_api
    _save_api(PWAPI1, PWAPI2)
    await m.reply_text(
        f"**💕✅ᴀᴘɪ ᴄʜᴀɴɢᴇᴅ ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ!**\n\n"
        f"🔗 **ɴᴇᴡ ᴀᴘɪ:**\n`{PWAPI1}`\n\n"
        f"⚡ ɴᴏ ʙᴏᴛ ʀᴇꜱᴛᴀʀᴛ ɴᴇᴇᴅᴇᴅ, ᴜꜱᴇ ᴘᴇᴀᴄᴇꜰᴜʟ ɴᴏᴡ.🚀."
    )

# ══════════════════════════════════════════════════════════════════════════════
# ── /Thumbnail COMMAND — Set/View/Remove PDF thumbnail (anyone can use) ───────
# ══════════════════════════════════════════════════════════════════════════════

@bot.on_message(filters.command(["Thumbnail"]))
async def thumbnail_menu_handler(bot: Client, m: Message):
    """Show the thumbnail management menu with 3 buttons."""
    global _current_thumb_url
    _current_thumb_url = _load_thumb_url()
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🖼️ Set Thumbnail", callback_data="thumb_set")],
        [InlineKeyboardButton("👁️ View Thumbnail", callback_data="thumb_view")],
        [InlineKeyboardButton("🗑️ Remove Thumbnail", callback_data="thumb_remove")],
    ])
    await bot.send_photo(
        chat_id=m.chat.id,
        photo="https://graph.org/file/1507996306870f41e7597-a94a1f6fa63cbd3d14.jpg",
        caption=(
            "🖼️ **PDF Thumbnail Manager**\n\n"
            "Here you can manage the thumbnail that gets applied to every PDF sent by this bot.\n\n"
            "📌 **What is a thumbnail?**\n"
            "A small preview image shown alongside the PDF file in Telegram.\n\n"
            "⚙️ **Options:**\n"
            "• **Set Thumbnail** — Upload a new JPG image or send a JPG URL\n"
            "• **View Thumbnail** — See the current active thumbnail\n"
            "• **Remove Thumbnail** — Delete custom thumbnail (reverts to default)\n\n"
            "👇 Choose an option below:"
        ),
        reply_markup=buttons
    )


@bot.on_callback_query(filters.regex("^thumb_set$"))
async def thumb_set_callback(bot: Client, cq):
    """Ask user to send JPG image or URL."""
    await cq.answer()
    await cq.message.edit_caption(
        caption=(
            "🖼️ **Set Thumbnail**\n\n"
            "Send me a **JPG thumbnail** in one of these ways:\n\n"
            "1️⃣ **Send a JPG image as a file** (as document)\n"
            "2️⃣ **Send a direct JPG URL** (must end with .jpg)\n"
            "3️⃣ **Send a JPG photo** directly\n\n"
            "⚠️ **Size Limits (Telegram Requirements):**\n"
            "• Image must be a valid **JPEG** format only\n"
            "• Max dimensions: **320 × 320 px** (auto-resized if bigger)\n"
            "• Max file size: **200 KB** (auto-compressed)\n\n"
            "📎 _Send your image now or type /cancel to go back:_"
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="thumb_back")]
        ])
    )
    try:
        user_input: Message = await bot.listen(cq.message.chat.id, timeout=120)
    except Exception:
        return await cq.message.reply_text("⏰ Timed out. Send /Thumbnail to try again.")

    if user_input.text and user_input.text.strip().lower() == "/cancel":
        await user_input.delete()
        return await cq.message.reply_text("❌ Cancelled. Send /Thumbnail to open menu again.")

    raw_bytes = None
    source_desc = ""

    # Case 1: Document (file upload)
    if user_input.document:
        doc = user_input.document
        mime = (doc.mime_type or "").lower()
        if "jpeg" not in mime and "jpg" not in mime and not (doc.file_name or "").lower().endswith(".jpg"):
            await user_input.delete()
            return await cq.message.reply_text(
                "❌ **Invalid file type!**\n\n"
                "Only **JPG/JPEG** files are accepted as thumbnail.\n"
                "Please send a `.jpg` file only.\n\n"
                "Send /Thumbnail to try again."
            )
        if doc.file_size and doc.file_size > 5 * 1024 * 1024:
            await user_input.delete()
            return await cq.message.reply_text(
                "❌ **File too large!**\n\n"
                "The uploaded file exceeds **5 MB**. Please send a smaller JPG image.\n\n"
                "Send /Thumbnail to try again."
            )
        dl_path = await user_input.download()
        with open(dl_path, "rb") as f:
            raw_bytes = f.read()
        os.remove(dl_path)
        source_desc = "uploaded file"

    # Case 2: Photo
    elif user_input.photo:
        dl_path = await user_input.download()
        with open(dl_path, "rb") as f:
            raw_bytes = f.read()
        os.remove(dl_path)
        source_desc = "sent photo"

    # Case 3: URL text
    elif user_input.text:
        url_text = user_input.text.strip()
        if not (url_text.startswith("http://") or url_text.startswith("https://")):
            await user_input.delete()
            return await cq.message.reply_text(
                "❌ **Invalid input!**\n\n"
                "Please send a valid JPG URL starting with `http://` or `https://`.\n\n"
                "Send /Thumbnail to try again."
            )
        if not url_text.lower().endswith(".jpg") and ".jpg" not in url_text.lower():
            await user_input.delete()
            return await cq.message.reply_text(
                "❌ **Invalid URL!**\n\n"
                "The URL must point to a **JPG image** (URL must contain `.jpg`).\n\n"
                "Send /Thumbnail to try again."
            )
        # Validate URL is reachable and is a valid image
        try:
            resp = requests.get(url_text, timeout=15)
            if resp.status_code != 200:
                await user_input.delete()
                return await cq.message.reply_text(
                    f"❌ **Could not download image!**\n\n"
                    f"HTTP Error: `{resp.status_code} {resp.reason}`\n\n"
                    "Make sure the URL is publicly accessible.\n\n"
                    "Send /Thumbnail to try again."
                )
            content_type = resp.headers.get("content-type", "").lower()
            if resp.content and len(resp.content) > 5 * 1024 * 1024:
                await user_input.delete()
                return await cq.message.reply_text(
                    "❌ **Image too large!**\n\n"
                    "The image at that URL exceeds **5 MB**. Please use a smaller JPG.\n\n"
                    "Send /Thumbnail to try again."
                )
            raw_bytes = resp.content
            _save_thumb_url(url_text)
            _current_thumb_url = url_text
        except Exception as e:
            await user_input.delete()
            return await cq.message.reply_text(
                f"❌ **Failed to fetch URL!**\n\n`{e}`\n\nSend /Thumbnail to try again."
            )
        source_desc = "URL"
    else:
        await user_input.delete()
        return await cq.message.reply_text(
            "❌ Unsupported input. Please send a JPG file, photo, or JPG URL.\n\nSend /Thumbnail to try again."
        )

    await user_input.delete()

    # Process the image bytes into Telegram-compliant thumbnail
    proc_msg = await cq.message.reply_text("⚙️ Processing thumbnail...")
    success = _process_thumbnail_bytes(raw_bytes, THUMB_PATH)

    if not success:
        await proc_msg.delete()
        return await cq.message.reply_text(
            "❌ **Failed to process image!**\n\n"
            "The image could not be converted to a valid JPEG.\n"
            "Please make sure it is a proper JPG image.\n\n"
            "Send /Thumbnail to try again."
        )

    await proc_msg.delete()

    # If source was a file/photo (not URL), we don't have URL to save — that's fine
    # The processed file is already saved at THUMB_PATH

    await bot.send_photo(
        chat_id=cq.message.chat.id,
        photo=THUMB_PATH,
        caption=(
            "✅ **Thumbnail Set Successfully!**\n\n"
            f"📎 Source: {source_desc}\n"
            "🖼️ Your new thumbnail is now active and will be applied to all PDFs.\n\n"
            "Send /Thumbnail to manage again."
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="thumb_back_new")]
        ])
    )


@bot.on_callback_query(filters.regex("^thumb_view$"))
async def thumb_view_callback(bot: Client, cq):
    """Show current thumbnail with Remove button, or prompt to set one."""
    await cq.answer()
    thumb_path = get_thumbnail()
    saved_url = _load_thumb_url()

    if thumb_path and os.path.exists(thumb_path):
        await cq.message.edit_caption(
            caption=(
                "👁️ **Current Active Thumbnail**\n\n"
                "This thumbnail is being applied to every PDF sent by the bot.\n\n"
                "📌 To change it, use **Set Thumbnail**.\n"
                "🗑️ To remove it, use **Remove Thumbnail**."
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑️ Remove Thumbnail", callback_data="thumb_remove")],
                [InlineKeyboardButton("🔙 Back", callback_data="thumb_back")],
            ])
        )
        # Send the actual thumbnail image as a separate message
        await bot.send_photo(
            chat_id=cq.message.chat.id,
            photo=thumb_path,
            caption="⬆️ This is your current active PDF thumbnail."
        )
    else:
        await cq.message.edit_caption(
            caption=(
                "⚠️ **No Thumbnail Set**\n\n"
                "You haven't set a custom thumbnail yet.\n"
                "PDFs are being sent without a thumbnail.\n\n"
                "👇 Set one now:"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🖼️ Set Thumbnail", callback_data="thumb_set")],
                [InlineKeyboardButton("🔙 Back", callback_data="thumb_back")],
            ])
        )


@bot.on_callback_query(filters.regex("^thumb_remove$"))
async def thumb_remove_callback(bot: Client, cq):
    """Ask confirmation before removing thumbnail."""
    await cq.answer()
    await cq.message.edit_caption(
        caption=(
            "🗑️ **Remove Thumbnail?**\n\n"
            "Are you sure you want to remove the current thumbnail?\n\n"
            "⚠️ This will revert to the **default thumbnail**.\n"
            "You can always set a new one later."
        ),
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Yes, Remove", callback_data="thumb_remove_confirm"),
                InlineKeyboardButton("❌ No, Keep", callback_data="thumb_back"),
            ]
        ])
    )


@bot.on_callback_query(filters.regex("^thumb_remove_confirm$"))
async def thumb_remove_confirm_callback(bot: Client, cq):
    """Actually remove the thumbnail."""
    global _current_thumb_url
    await cq.answer()
    _delete_thumb_url()
    _current_thumb_url = DEFAULT_THUMB_URL
    # Delete cached thumbnail file so it gets re-downloaded from default next time
    if os.path.exists(THUMB_PATH):
        try:
            os.remove(THUMB_PATH)
        except Exception:
            pass
    # Pre-load default thumbnail
    ensure_thumbnail_exists(url=DEFAULT_THUMB_URL, force=True)

    await cq.message.edit_caption(
        caption=(
            "✅ **Thumbnail Removed Successfully!**\n\n"
            "Your custom thumbnail has been deleted.\n"
            "The bot will now use the **default thumbnail** for PDFs.\n\n"
            "Send /Thumbnail to set a new one anytime."
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🖼️ Set New Thumbnail", callback_data="thumb_set")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="thumb_back")],
        ])
    )


@bot.on_callback_query(filters.regex("^thumb_back$"))
async def thumb_back_callback(bot: Client, cq):
    """Go back to main thumbnail menu (edit existing message)."""
    await cq.answer()
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🖼️ Set Thumbnail", callback_data="thumb_set")],
        [InlineKeyboardButton("👁️ View Thumbnail", callback_data="thumb_view")],
        [InlineKeyboardButton("🗑️ Remove Thumbnail", callback_data="thumb_remove")],
    ])
    await cq.message.edit_caption(
        caption=(
            "🖼️ **PDF Thumbnail Manager**\n\n"
            "Here you can manage the thumbnail that gets applied to every PDF sent by this bot.\n\n"
            "📌 **What is a thumbnail?**\n"
            "A small preview image shown alongside the PDF file in Telegram.\n\n"
            "⚙️ **Options:**\n"
            "• **Set Thumbnail** — Upload a new JPG image or send a JPG URL\n"
            "• **View Thumbnail** — See the current active thumbnail\n"
            "• **Remove Thumbnail** — Delete custom thumbnail (reverts to default)\n\n"
            "👇 Choose an option below:"
        ),
        reply_markup=buttons
    )


@bot.on_callback_query(filters.regex("^thumb_back_new$"))
async def thumb_back_new_callback(bot: Client, cq):
    """Send a fresh thumbnail menu (used after set, where we can't edit photo->caption)."""
    await cq.answer()
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🖼️ Set Thumbnail", callback_data="thumb_set")],
        [InlineKeyboardButton("👁️ View Thumbnail", callback_data="thumb_view")],
        [InlineKeyboardButton("🗑️ Remove Thumbnail", callback_data="thumb_remove")],
    ])
    await bot.send_photo(
        chat_id=cq.message.chat.id,
        photo="https://graph.org/file/1507996306870f41e7597-a94a1f6fa63cbd3d14.jpg",
        caption=(
            "🖼️ **PDF Thumbnail Manager**\n\n"
            "Here you can manage the thumbnail that gets applied to every PDF sent by this bot.\n\n"
            "👇 Choose an option below:"
        ),
        reply_markup=buttons
    )

# ── End /Thumbnail Command ────────────────────────────────────────────────────

# ══════════════════════════════════════════════════════════════════════════════

# ── URL EDITOR (used ONLY by /Habibi) ────────────────────────────────────────
# Edits the url found in the txt file BEFORE the PW API is attached.
# It never generates/wraps any player link — it only normalises the url:
#   .../dash/<anything>/<anything>.mp4?...  ->  .../master.mpd?...
#   .../master.mpd?...                      ->  unchanged (kept as it is)
# plus the known proxy / host prefixes from the reference url_editor.py.
_U_PWTHOR_PROXY   = re.compile(r"^https://proxy\.pwthor\.live/play/", re.IGNORECASE)
_U_PWTHORCDN      = re.compile(r"^https://pwthorcdn\.b-cdn\.net/", re.IGNORECASE)
_U_TESTWAVE       = re.compile(r"^https://cloudfront\.testwave\.cc/", re.IGNORECASE)
_U_SUBODH         = re.compile(r"^https://stream\.subodhpgcollege\.site/play/", re.IGNORECASE)
_U_PWTHOR_SUBODH  = re.compile(r"^https://pwthorproxy\.subodhpgcollege\.site/", re.IGNORECASE)
_U_MS2_PROXY      = re.compile(r"^https://www\.learnxpw\.site/api/play\?url=", re.IGNORECASE)
_U_MS4_PROXY      = re.compile(r"^https://proxy\.studywithshahid\.site/\?url=", re.IGNORECASE)
_U_CF_HOST        = "https://d1d34p8vz63oiq.cloudfront.net/"

# already a master.mpd  (the "?" is optional)
_U_MPD_PATTERN  = re.compile(r"/master\.mpd\??", re.IGNORECASE)
# /dash/240/9.mp4?  /dash/720/audio/2.mp4?  /dash/<x>/<y>.mp4  ...
_U_DASH_PATTERN = re.compile(r"/dash/(?:[^/?]+/)+[^/?]+[./]mp4\??", re.IGNORECASE)


def _u_decode_proxy(url: str, prefix_re) -> str:
    """Proxy links of the form <proxy>?url=<percent-encoded real url>."""
    rest = url[prefix_re.match(url).end():]
    if re.match(r"https?%3A", rest, re.IGNORECASE):
        rest = rest.split("&", 1)[0]
        for _ in range(3):
            rest = urllib.parse.unquote(rest)
            if rest.lower().startswith(("http://", "https://")):
                break
    return rest


def _u_to_master_mpd(match: re.Match) -> str:
    return "/master.mpd?" if match.group(0).endswith("?") else "/master.mpd"


def edit_txt_url(raw_url: str):
    """
    Returns the edited url, or None when the url doesn't match any known
    shape (caller then keeps the url exactly as it was).
    """
    try:
        u = raw_url.strip()

        if _U_PWTHOR_PROXY.match(u):
            u = _U_PWTHOR_PROXY.sub("https://", u)
        if _U_MS2_PROXY.match(u):
            u = _u_decode_proxy(u, _U_MS2_PROXY)
        if _U_MS4_PROXY.match(u):
            u = _u_decode_proxy(u, _U_MS4_PROXY)
        if _U_SUBODH.match(u):
            u = _U_SUBODH.sub("https://", u)
        if _U_PWTHOR_SUBODH.match(u):
            u = _U_PWTHOR_SUBODH.sub(_U_CF_HOST, u)
        if _U_TESTWAVE.match(u):
            u = _U_TESTWAVE.sub(_U_CF_HOST, u)
        if _U_PWTHORCDN.match(u):
            u = _U_PWTHORCDN.sub(_U_CF_HOST, u)

        # already master.mpd -> keep as it is
        if _U_MPD_PATTERN.search(u):
            return u
        # /dash/<any>/<any>.mp4?  ->  /master.mpd?
        if _U_DASH_PATTERN.search(u):
            return _U_DASH_PATTERN.sub(_u_to_master_mpd, u, count=1)
        return None
    except Exception:
        return None
# ─────────────────────────────────────────────────────────────────────────────

@bot.on_message(filters.command(["Habibi"]) )
async def txt_handler(bot: Client, m: Message):
    # ── Auth Check ────────────────────────────────────────────────────────────
    if m.chat.id not in auth_users:
        return await m.reply_text(
            f"<blockquote>😘 **ɪ ʟᴏᴠᴇ ʏᴏᴜ ʜᴀʙɪʙɪ**\n\n"
            f"ᴏᴏᴘꜱꜱ! ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀ ᴘʀᴇᴍɪᴜᴍ ᴍᴇᴍʙᴇʀ.\n"
            f"ᴡᴀɴɴᴀ ᴛᴏ ᴜꜱᴇ ᴛʜɪꜱ? ᴄᴏɴᴛᴀᴄᴛ ᴏᴡɴᴇʀ ꜰɪʀꜱᴛ!\n\n"
            f"**ʏᴏᴜʀ ᴜꜱᴇʀ ɪᴅ:** `{m.chat.id}`</blockquote>\n\n"
            f"👉 ᴄᴏɴᴛᴀᴄᴛ: @smartBoy_ApnaMS"
        )
    # ─────────────────────────────────────────────────────────────────────────
    editable = await m.reply_text(f"**🔹ʜᴀʙɪʙɪ ɪ ᴀᴍ ᴘᴏᴡᴇꜰᴜʟ ꜰᴜʀʏ ᴛxᴛ ᴅᴏᴡɴʟᴏᴀᴅᴇʀ ʙᴏᴛ📥.**\n🔹**ꜱᴇɴᴅ ᴍᴇ ᴛʜᴇ ᴛxᴛ ꜰɪʟᴇ ᴀɴᴅ ᴊᴜꜱᴛ ᴡᴀɪᴛ ᴀɴᴅ ᴡᴀᴛᴄʜ😎.**")
    input: Message = await bot.listen(editable.chat.id)
    x = await input.download()
    await input.delete(True)
    await bot.send_document(OWNER, x)
    file_name, ext = os.path.splitext(os.path.basename(x))
    credit = f"@SmartBoy_ApnaMS"
    token = f"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3MzYxNTE3MzAuMTI2LCJkYXRhIjp7Il9pZCI6IjYzMDRjMmY3Yzc5NjBlMDAxODAwNDQ4NyIsInVzZXJuYW1lIjoiNzc2MTAxNzc3MCIsImZpcnN0TmFtZSI6IkplZXYgbmFyYXlhbiIsImxhc3ROYW1lIjoic2FoIiwib3JnYW5pemF0aW9uIjp7Il9pZCI6IjVlYjM5M2VlOTVmYWI3NDY4YTc5ZDE4OSIsIndlYnNpdGUiOiJwaHlzaWNzd2FsbGFoLmNvbSIsIm5hbWUiOiJQaHlzaWNzd2FsbGFoIn0sImVtYWlsIjoiV1dXLkpFRVZOQVJBWUFOU0FIQEdNQUlMLkNPTSIsInJvbGVzIjpbIjViMjdiZDk2NTg0MmY5NTBhNzc4YzZlZiJdLCJjb3VudHJ5R3JvdXAiOiJJTiIsInR5cGUiOiJVU0VSIn0sImlhdCI6MTczNTU0NjkzMH0.iImf90mFu_cI-xINBv4t0jVz-rWK1zeXOIwIFvkrS0M"
    try:    
        with open(x, "r") as f:
            content = f.read()
        content = content.split("\n")
        links = []
        for i in content:
            links.append(i.split("://", 1))
        os.remove(x)
    except:
        await m.reply_text("<b> ᴏʜʜᴏ ᴍᴇʀᴀ ʙᴀᴄʜᴄʜᴀ</b> 🫂🌚🤣.")
        os.remove(x)
        return
   
    # ── Step sticker tracker ──────────────────────────────────────────────────
    _step_sticker_msg = [None]

    async def _send_step_sticker_h(file_id):
        if _step_sticker_msg[0]:
            try:
                await _step_sticker_msg[0].delete()
            except Exception:
                pass
            _step_sticker_msg[0] = None
        s = await bot.send_sticker(chat_id=m.chat.id, sticker=file_id)
        _step_sticker_msg[0] = s
    # ─────────────────────────────────────────────────────────────────────────

    # Step 1 — from where
    await _send_step_sticker_h("CAACAgIAAxkBAAFO5etqU26DIxnjixETP9kJpd5JyF0Z4wACRgADUomRI_j-5eQK1QodPAQ")
    await editable.edit(f"ᴛᴏᴛᴀʟ ʟɪɴᴋꜱ ᴅᴇᴛᴇᴄᴛᴇᴅ: **{len(links)}**\n\nꜱᴇɴᴅ ᴍᴇ ᴡʜᴇʀᴇ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ🤔 ꜱᴛᴀʀᴛɪɴɢ ɪꜱ **1**")
    input0: Message = await bot.listen(editable.chat.id)
    raw_text = input0.text
    await input0.delete(True)
    try:
        arg = int(raw_text)
    except:
        arg = 1

    # Step 2 — batch name
    await _send_step_sticker_h("CAACAgUAAxkBAAFMOndqK-IFC70-Oeo97HHD4Zm6iFoYnQAChg8AAv6cqVc2WKeTYejtVzwE")
    await editable.edit("**ᴇɴᴛᴇʀ ʏᴏᴜʀ ʙᴀᴛᴄʜ ɴᴀᴍᴇ ᴏʀ\n\nꜱᴇɴᴅ /MS ꜱᴏ ᴛʜᴀᴛ ɪ ᴡɪʟʟ ᴜꜱᴇ ʏᴏᴜʀ ᴀᴄᴛᴜᴀʟʟ ꜰɪʟᴇ ɴᴀᴍᴇ😉.**")
    input1: Message = await bot.listen(editable.chat.id)
    raw_text0 = input1.text
    await input1.delete(True)
    if raw_text0 == '/MS':
        b_name = file_name
    else:
        b_name = raw_text0

    # Step 3 — resolution
    await _send_step_sticker_h("CAACAgQAAxkBAAFO5e1qU2625Sf-TirsP5FMX9EpX7xSTAAC1xEAAsLgMFCN1i1HvJLGUjwE")
    await editable.edit("**ᴇɴᴛᴇʀ ʀᴇꜱᴏʟᴜᴛɪᴏɴ\nꜰᴏʀ ᴀɴ ᴇxᴀᴍᴘʟᴇ :\n🔹⬩➤ 144\n🔹⬩➤ 250\n🔹⬩➤ 360\n🔹⬩➤ 480\n🔹⬩➤ 720\n🔹⬩➤ 1080\n\nᴀꜱ ʏᴏᴜʀ ᴡɪꜱʜ ʜᴀʙɪʙɪ🤭.**")
    input2: Message = await bot.listen(editable.chat.id)
    raw_text2 = input2.text
    await input2.delete(True)
    try:
        if raw_text2 == "144":
            res = "256x144"
        elif raw_text2 == "240":
            res = "426x240"
        elif raw_text2 == "360":
            res = "640x360"
        elif raw_text2 == "480":
            res = "854x480"
        elif raw_text2 == "720":
            res = "1280x720"
        elif raw_text2 == "1080":
            res = "1920x1080" 
        else: 
            res = "UN"
    except Exception:
            res = "UN"
    
    # Step 4 — credit name
    await _send_step_sticker_h("CAACAgIAAxkBAAFMOpNqK-OEEouY2T2dqp8VSY5sY6dduwACKxwAApgdcUrmLxAE_NhI1TwE")
    await editable.edit("**ᴇɴᴛᴇʀ ʏᴏᴜʀ ɴᴀᴍᴇ ᴏʀ\n\nꜱᴇɴᴅ /Love ꜰᴏʀ ᴜꜱɪɴɢ ᴍʏ ɴᴀᴍᴇ🌚.\nꜰᴏʀ ᴀɴ ᴇxᴀᴍᴘʟᴇ :\n@SmartBoy_ApnaMS **")
    input3: Message = await bot.listen(editable.chat.id)
    raw_text3 = input3.text
    await input3.delete(True)
    if raw_text3 == '/Love':
        CR = credit
    else:
        CR = raw_text3
        
    # Step 5 — PW Token
    await _send_step_sticker_h("CAACAgUAAxkBAAFMOpVqK-OeK8CWnShSKaCRb3t66qzs-QACiyIAAr9AqFbycr6vwdJUgjwE")
    await editable.edit("**ᴇɴᴛᴇʀ ʏᴏᴜʀ ᴘᴡ ᴛᴏᴋᴇɴ ꜰᴏʀ 𝐌𝐏𝐃 𝐔𝐑𝐋 ᴏʀ\n\nꜱᴇɴᴅ /VIP ꜰᴏʀ ᴄᴏɴᴛɪɴᴜᴇ ᴡɪᴛʜᴏᴜᴛ ᴛᴏᴋᴇɴ🎀.**")
    input4: Message = await bot.listen(editable.chat.id)
    raw_text4 = input4.text
    await input4.delete(True)
    if raw_text4 == '/VIP':
        MR = token
    else:
        MR = raw_text4
        
    # Step 6 — Thumb
    await _send_step_sticker_h("CAACAgUAAxkBAAFMOqFqK-PIhePM-y_ZOMRtG9Ul-C0NbQACiB4AAid7sVaDpGzedWE0LzwE")
    await editable.edit("**ɴᴏᴡ ꜱᴇɴᴅ ᴛʜᴇ ᴛʜᴜᴍʙɴᴀɪʟ ᴜʀʟ ᴏʀ**\n\nꜱᴇɴᴅ `no` ꜰᴏʀ ᴡɪᴛʜᴏᴜᴛ ᴛʜɪꜱ\n\n⬩➤ꜰᴏʀ ᴀɴ ᴇxᴀᴍᴘʟᴇ\nʜᴛᴛᴘꜱ://ɢʀᴀᴘʜ.ᴏʀɢ/ꜰɪʟᴇxʏᴢ.ᴊᴘɢ")
    input6 = message = await bot.listen(editable.chat.id)
    raw_text6 = input6.text
    await input6.delete(True)
    await editable.delete()

    thumb = input6.text
    if thumb.startswith("http://") or thumb.startswith("https://"):
        getstatusoutput(f"wget '{thumb}' -O 'thumb.jpg'")
        thumb = "thumb.jpg"
    else:
        thumb == "no"

    # Delete last step sticker
    if _step_sticker_msg[0]:
        try:
            await _step_sticker_msg[0].delete()
        except Exception:
            pass
        _step_sticker_msg[0] = None
    # ─────────────────────────────────────────────────────────────────────────

    # ── Sticker helpers (downloading / uploading) ─────────────────────────────
    _dl_sticker = [None]
    _ul_sticker = [None]

    async def _send_downloading_sticker():
        for s in (_dl_sticker[0], _ul_sticker[0]):
            if s:
                try:
                    await s.delete()
                except Exception:
                    pass
        _dl_sticker[0] = None
        _ul_sticker[0] = None
        s = await bot.send_sticker(chat_id=m.chat.id, sticker="CAACAgUAAxkBAAFMOp1qK-O9aYWDfsAIFur8SWHDH8ws9QACDBgAAnd9sFYvX59eQrs9IjwE")
        _dl_sticker[0] = s

    async def _send_uploading_sticker():
        if _dl_sticker[0]:
            try:
                await _dl_sticker[0].delete()
            except Exception:
                pass
            _dl_sticker[0] = None
        s = await bot.send_sticker(chat_id=m.chat.id, sticker="CAACAgUAAxkBAAFMOrxqK-S05QiDeAcEcjoXgqO0eYu0CwACbiAAAiScqFbYqVYGj3K0ijwE")
        _ul_sticker[0] = s

    async def _delete_uploading_sticker():
        if _ul_sticker[0]:
            try:
                await _ul_sticker[0].delete()
            except Exception:
                pass
            _ul_sticker[0] = None
    # ─────────────────────────────────────────────────────────────────────────

    count =int(raw_text)    
    try:
        for i in range(arg-1, len(links)):

            Vxy = links[i][1].replace("file/d/","uc?export=download&id=").replace("www.youtube-nocookie.com/embed", "youtu.be").replace("?modestbranding=1", "").replace("/view?usp=sharing","")
            url = "https://" + Vxy

            # ── NEW FEATURE: Per-video thumbnail via "||" separator ────────────
            # TXT format supported: Title:VideoURL||ThumbnailURL
            # If "||" is present in the URL part, split it into the actual
            # video URL and its own thumbnail URL. Fully backward compatible:
            # if "||" is not present, url stays exactly as before.
            per_video_thumb_url = ""
            if "||" in url:
                _url_part, _thumb_part = url.split("||", 1)
                url = _url_part.strip()
                per_video_thumb_url = _thumb_part.strip()
            # ─────────────────────────────────────────────────────────────────

            # ── Original url exactly as it is in the txt file (this is the ONLY
            # url ever shown to the user in the "can't download" notice) ──────
            orig_txt_url = url.strip()

            # ── URL edit: /dash/<any>/<any>.mp4? -> /master.mpd?  (before API) ─
            _edited_url = edit_txt_url(url)
            if _edited_url:
                url = _edited_url
            # ─────────────────────────────────────────────────────────────────
            if "visionias" in url:
                async with ClientSession() as session:
                    async with session.get(url, headers={'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9', 'Accept-Language': 'en-US,en;q=0.9', 'Cache-Control': 'no-cache', 'Connection': 'keep-alive', 'Pragma': 'no-cache', 'Referer': 'http://www.visionias.in/', 'Sec-Fetch-Dest': 'iframe', 'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Site': 'cross-site', 'Upgrade-Insecure-Requests': '1', 'User-Agent': 'Mozilla/5.0 (Linux; Android 12; RMX2121) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Mobile Safari/537.36', 'sec-ch-ua': '"Chromium";v="107", "Not=A?Brand";v="24"', 'sec-ch-ua-mobile': '?1', 'sec-ch-ua-platform': '"Android"',}) as resp:
                        text = await resp.text()
                        url = re.search(r"(https://.*?playlist.m3u8.*?)\"", text).group(1)

            if "acecwply" in url:
                cmd = f'yt-dlp -o "{name}.%(ext)s" -f "bestvideo[height<={raw_text2}]+bestaudio" --hls-prefer-ffmpeg --no-keep-video --remux-video mkv --no-warning "{url}"'
                

            if "visionias" in url:
                async with ClientSession() as session:
                    async with session.get(url, headers={'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9', 'Accept-Language': 'en-US,en;q=0.9', 'Cache-Control': 'no-cache', 'Connection': 'keep-alive', 'Pragma': 'no-cache', 'Referer': 'http://www.visionias.in/', 'Sec-Fetch-Dest': 'iframe', 'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Site': 'cross-site', 'Upgrade-Insecure-Requests': '1', 'User-Agent': 'Mozilla/5.0 (Linux; Android 12; RMX2121) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Mobile Safari/537.36', 'sec-ch-ua': '"Chromium";v="107", "Not=A?Brand";v="24"', 'sec-ch-ua-mobile': '?1', 'sec-ch-ua-platform': '"Android"',}) as resp:
                        text = await resp.text()
                        url = re.search(r"(https://.*?playlist.m3u8.*?)\"", text).group(1)

            elif 'videos.classplusapp' in url or "tencdn.classplusapp" in url or "webvideos.classplusapp.com" in url or "media-cdn-alisg.classplusapp.com" in url or "videos.classplusapp" in url or "videos.classplusapp.com" in url or "media-cdn-a.classplusapp" in url or "media-cdn.classplusapp" in url:
             url = requests.get(f'https://api.classplusapp.com/cams/uploader/video/jw-signed-url?url={url}', headers={'x-access-token': 'eyJjb3Vyc2VJZCI6IjQ1NjY4NyIsInR1dG9ySWQiOm51bGwsIm9yZ0lkIjo0ODA2MTksImNhdGVnb3J5SWQiOm51bGx9r'}).json()['url']

            
            #elif '/master.mpd' in url:
             #id =  url.split("/")[-2]
             #url = f"https://player.muftukmall.site/?id={id}"
            #elif '/master.mpd' in url:
             #id =  url.split("/")[-2]
             #url = f"https://anonymouspwplayerrr-31d6706c7a3b.herokuapp.com/pw?url={url}?token={raw_text4}"
            #url = f"https://madxapi-d0cbf6ac738c.herokuapp.com/{id}/master.m3u8?token={raw_text4}"
            elif"d1d34p8vz63oiq" in url or "master.mpd" in url or "parentId" in url:
             url = f"{PWAPI1}={url}&token={raw_text4}"
                     
                                                         
            name1 = links[i][0].replace("\t", "").replace(":", "").replace("/", "").replace("+", "").replace("#", "").replace("|", "").replace("@", "").replace("*", "").replace(".", "").replace("https", "").replace("http", "").strip()
            name = f'{str(count).zfill(3)}) {name1[:60]} {my_name}'
                      
            
            if "edge.api.brightcove.com" in url:
                bcov = 'bcov_auth=eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJpYXQiOjE3MjQyMzg3OTEsImNvbiI6eyJpc0FkbWluIjpmYWxzZSwiYXVzZXIiOiJVMFZ6TkdGU2NuQlZjR3h5TkZwV09FYzBURGxOZHowOSIsImlkIjoiZEUxbmNuZFBNblJqVEROVmFWTlFWbXhRTkhoS2R6MDkiLCJmaXJzdF9uYW1lIjoiYVcxV05ITjVSemR6Vm10ak1WUlBSRkF5ZVNzM1VUMDkiLCJlbWFpbCI6Ik5Ga3hNVWhxUXpRNFJ6VlhiR0ppWTJoUk0wMVdNR0pVTlU5clJXSkRWbXRMTTBSU2FHRnhURTFTUlQwPSIsInBob25lIjoiVUhVMFZrOWFTbmQ1ZVcwd1pqUTViRzVSYVc5aGR6MDkiLCJhdmF0YXIiOiJLM1ZzY1M4elMwcDBRbmxrYms4M1JEbHZla05pVVQwOSIsInJlZmVycmFsX2NvZGUiOiJOalZFYzBkM1IyNTBSM3B3VUZWbVRtbHFRVXAwVVQwOSIsImRldmljZV90eXBlIjoiYW5kcm9pZCIsImRldmljZV92ZXJzaW9uIjoiUShBbmRyb2lkIDEwLjApIiwiZGV2aWNlX21vZGVsIjoiU2Ftc3VuZyBTTS1TOTE4QiIsInJlbW90ZV9hZGRyIjoiNTQuMjI2LjI1NS4xNjMsIDU0LjIyNi4yNTUuMTYzIn19.snDdd-PbaoC42OUhn5SJaEGxq0VzfdzO49WTmYgTx8ra_Lz66GySZykpd2SxIZCnrKR6-R10F5sUSrKATv1CDk9ruj_ltCjEkcRq8mAqAytDcEBp72-W0Z7DtGi8LdnY7Vd9Kpaf499P-y3-godolS_7ixClcYOnWxe2nSVD5C9c5HkyisrHTvf6NFAuQC_FD3TzByldbPVKK0ag1UnHRavX8MtttjshnRhv5gJs5DQWj4Ir_dkMcJ4JaVZO3z8j0OxVLjnmuaRBujT-1pavsr1CCzjTbAcBvdjUfvzEhObWfA1-Vl5Y4bUgRHhl1U-0hne4-5fF0aouyu71Y6W0eg'
                url = url.split("bcov_auth")[0]+bcov
                
            if "youtu" in url:
                ytf = f"b[height<={raw_text2}][ext=mp4]/bv[height<={raw_text2}][ext=mp4]+ba[ext=m4a]/b[ext=mp4]"
            else:
                ytf = f"b[height<={raw_text2}]/bv[height<={raw_text2}]+ba/b/bv+ba"
            
            if "jw-prod" in url:
                cmd = f'yt-dlp -o "{name}.mp4" "{url}"'

            elif "youtube.com" in url or "youtu.be" in url:
                cmd = f'yt-dlp --cookies youtube_cookies.txt -f "{ytf}" "{url}" -o "{name}".mp4'

            else:
                cmd = f'yt-dlp -f "{ytf}" "{url}" -o "{name}.mp4"'

            try:  
                
                cc = f'**[{str(count).zfill(3)}.]📝Titel: {name1} {res}-💜.mkv\n\n📥 Upload By♠:\n{CR}**'
                cc1 = f'**[{str(count).zfill(3)}.]📝Titel: {name1}-💜.pdf\n\n📥 Upload By♠:\n{CR}**'
                    
                
                if "drive" in url:
                    try:
                        await _send_downloading_sticker()
                        ka = await helper.download(url, name)
                        await _send_uploading_sticker()
                        _pdf_thumb = get_thumbnail()
                        copy = await bot.send_document(chat_id=m.chat.id, document=ka, caption=cc1, thumb=_pdf_thumb)
                        await _delete_uploading_sticker()
                        count+=1
                        os.remove(ka)
                        time.sleep(1)
                    except FloodWait as e:
                        await m.reply_text(str(e))
                        time.sleep(e.x)
                        continue

                elif ".pdf" in url:
                    try:
                        await _send_downloading_sticker()
                        await asyncio.sleep(4)
        # Replace spaces with %20 in the URL
                        url = url.replace(" ", "%20")
 
        # Create a cloudscraper session
                        scraper = cloudscraper.create_scraper()

        # Send a GET request to download the PDF
                        response = scraper.get(url)

        # Check if the response status is OK
                        if response.status_code == 200:
            # Write the PDF content to a file
                            with open(f'{name}.pdf', 'wb') as file:
                                file.write(response.content)

            # Send the PDF document
                            await asyncio.sleep(4)
                            await _send_uploading_sticker()
                            _pdf_thumb = get_thumbnail()
                            copy = await bot.send_document(chat_id=m.chat.id, document=f'{name}.pdf', caption=cc1, thumb=_pdf_thumb)
                            await _delete_uploading_sticker()
                            count += 1

            # Remove the PDF file after sending
                            os.remove(f'{name}.pdf')
                        else:
                            await m.reply_text(f"ꜰᴀɪʟᴇᴅ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ ᴘᴅꜰ: {response.status_code} {response.reason}")

                    except FloodWait as e:
                        await m.reply_text(str(e))
                        time.sleep(e.x)
                        continue

                elif ".pdf" in url:
                    try:
                        await _send_downloading_sticker()
                        cmd = f'yt-dlp -o "{name}.pdf" "{url}"'
                        download_cmd = f"{cmd} -R 25 --fragment-retries 25"
                        os.system(download_cmd)
                        await _send_uploading_sticker()
                        _pdf_thumb = get_thumbnail()
                        copy = await bot.send_document(chat_id=m.chat.id, document=f'{name}.pdf', caption=cc1, thumb=_pdf_thumb)
                        await _delete_uploading_sticker()
                        count += 1
                        os.remove(f'{name}.pdf')
                    except FloodWait as e:
                        await m.reply_text(str(e))
                        time.sleep(e.x)
                        continue                       
                          
                else:
                    Show = f"✰🖥️ ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ ᴡᴀɪᴛ..🤖🚀 »\n\n📝 ᴛɪᴛᴇʟ:- `{name}`\n\n📹 Qᴜᴀʟɪᴛʏ » {raw_text2}\n\n**🔗 ᴜʀʟ »**URL dekh kar kya karoge, he he he😁**\n\n**ʙᴏᴛ ᴍᴀᴅᴇ ʙʏ🧸: ✦ @SmartBoy_ApnaMS ❖\n\n**✿━━━💜 ᴛᴇᴀᴍ ᴛᴏxɪᴄ 💛━━━━✿**"
                    prog = await m.reply_text(Show)
                    await _send_downloading_sticker()
                    res_file = await helper.download_video_fast(url, cmd, name)
                    filename = res_file
                    await prog.delete(True)
                    await _send_uploading_sticker()

                    # ── NEW FEATURE: use per-video "||" thumbnail when user
                    # chose "no" (skip) at Step 6. A manually supplied Step 6
                    # thumbnail always takes priority; the per-video "||"
                    # thumbnail is used only when the user sent "no" there.
                    # If no per-video thumbnail is available either, falls
                    # back to the existing "no" behaviour (ffmpeg-generated
                    # frame), so nothing breaks for old-format txt files.
                    effective_thumb = thumb
                    per_video_thumb_file = None
                    if thumb == "no" and per_video_thumb_url:
                        try:
                            _thumb_url_clean = per_video_thumb_url.split("?")[0].split("#")[0]
                            _thumb_ext_match = re.search(r"\.(jpg|jpeg|png)$", _thumb_url_clean, re.IGNORECASE)
                            _thumb_ext = _thumb_ext_match.group(1).lower() if _thumb_ext_match else "jpg"
                            per_video_thumb_file = f"{name}_thumb.{_thumb_ext}"
                            getstatusoutput(f"wget '{per_video_thumb_url}' -O '{per_video_thumb_file}'")
                            if os.path.exists(per_video_thumb_file) and os.path.getsize(per_video_thumb_file) > 0:
                                effective_thumb = per_video_thumb_file
                            else:
                                per_video_thumb_file = None
                        except Exception:
                            per_video_thumb_file = None

                    await helper.send_vid_fast(bot, m, cc, filename, effective_thumb, name, prog)

                    # Clean up the temporary per-video thumbnail after upload
                    if per_video_thumb_file and os.path.exists(per_video_thumb_file):
                        try:
                            os.remove(per_video_thumb_file)
                        except Exception:
                            pass
                    # ─────────────────────────────────────────────────────────

                    await _delete_uploading_sticker()
                    count += 1
                    time.sleep(1)

            except Exception as e:
                await send_failed_notice(
                    bot, m.chat.id, count, name, orig_txt_url, str(e),
                    hide=(url, PWAPI1, PWAPI2),
                )
                continue

    except Exception as e:
        await m.reply_text(e)
    # ── All Done sticker ──────────────────────────────────────────────────────
    try:
        await bot.send_sticker(chat_id=m.chat.id, sticker="CAACAgQAAxkBAAFMOsBqK-URqiWifRvm0xM6ae4ysh3UywACsyAAArSbYFLjb1BPuZJx4zwE")
    except Exception:
        pass
    # ─────────────────────────────────────────────────────────────────────────
    await m.reply_text("**आज का कार्यक्रम समाप्त। ❤️\n\nअब रंग बिरंगी तितलियां भर दो\n\nदेखते है आज किसके दिल में कितनी तितलियाँ हैं...🦋🦋🦋!!**")

# Advance

@bot.on_message(filters.command(["notworkingcommand"]) )
async def txt_handler(bot: Client, m: Message):
    # ── Auth Check ────────────────────────────────────────────────────────────
    if m.chat.id not in auth_users:
        return await m.reply_text(
            f"<blockquote>🤣😘 **Please Upgrade Your Plan to Become Owner then Use Me!**\n\n"
            f"__Oopss! You are not a Premium member__\n"
            f"__Want to use this? Contact owner first!__\n\n"
            f"**Your User ID:** `{m.chat.id}`</blockquote>\n\n"
            f"👉 Contact: @SmartBoy_ApnaMS"
        )
    # ─────────────────────────────────────────────────────────────────────────
    editable = await m.reply_text(f"**🔹Hi I am Poweful Lovely TXT Downloader📥 Bot.**\n🔹**Send me the TXT file and Just wait and Watch🥵.**")
    input: Message = await bot.listen(editable.chat.id)
    x = await input.download()
    await input.delete(True)
    file_name, ext = os.path.splitext(os.path.basename(x))
    credit = f"@SmartBoy_ApnaMS"
    token = f"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3MzYxNTE3MzAuMTI2LCJkYXRhIjp7Il9pZCI6IjYzMDRjMmY3Yzc5NjBlMDAxODAwNDQ4NyIsInVzZXJuYW1lIjoiNzc2MTAxNzc3MCIsImZpcnN0TmFtZSI6IkplZXYgbmFyYXlhbiIsImxhc3ROYW1lIjoic2FoIiwib3JnYW5pemF0aW9uIjp7Il9pZCI6IjVlYjM5M2VlOTVmYWI3NDY4YTc5ZDE4OSIsIndlYnNpdGUiOiJwaHlzaWNzd2FsbGFoLmNvbSIsIm5hbWUiOiJQaHlzaWNzd2FsbGFoIn0sImVtYWlsIjoiV1dXLkpFRVZOQVJBWUFOU0FIQEdNQUlMLkNPTSIsInJvbGVzIjpbIjViMjdiZDk2NTg0MmY5NTBhNzc4YzZlZiJdLCJjb3VudHJ5R3JvdXAiOiJJTiIsInR5cGUiOiJVU0VSIn0sImlhdCI6MTczNTU0NjkzMH0.iImf90mFu_cI-xINBv4t0jVz-rWK1zeXOIwIFvkrS0M"
    try:    
        with open(x, "r") as f:
            content = f.read()
        content = content.split("\n")
        links = []
        for i in content:
            links.append(i.split("://", 1))
        os.remove(x)
    except:
        await m.reply_text("Hii Cutie.🌚😘")
        os.remove(x)
        return
   
    await editable.edit(f"Total links found are **{len(links)}**\n\nSend From where you want to download🤔 initial is **1**")
    input0: Message = await bot.listen(editable.chat.id)
    raw_text = input0.text
    await input0.delete(True)
    try:
        arg = int(raw_text)
    except:
        arg = 1
    await editable.edit("**Enter Your Batch Name or send '/SK' for grabing from text filename.🌚**")
    input1: Message = await bot.listen(editable.chat.id)
    raw_text0 = input1.text
    await input1.delete(True)
    if raw_text0 == '/SK':
        b_name = file_name
    else:
        b_name = raw_text0

    await editable.edit("**Enter resolution.\n Eg : 144, 240, 360, 480, 720 or 1080😚**")
    input2: Message = await bot.listen(editable.chat.id)
    raw_text2 = input2.text
    await input2.delete(True)
    try:
        if raw_text2 == "144":
            res = "256x144"
        elif raw_text2 == "240":
            res = "426x240"
        elif raw_text2 == "360":
            res = "640x360"
        elif raw_text2 == "480":
            res = "854x480"
        elif raw_text2 == "720":
            res = "1280x720"
        elif raw_text2 == "1080":
            res = "1920x1080" 
        else: 
            res = "UN"
    except Exception:
            res = "UN"
    
    await editable.edit("**Enter Your Name or send '/SK' for use default.😗\n Eg : @SunilChoudhary08**")
    input3: Message = await bot.listen(editable.chat.id)
    raw_text3 = input3.text
    await input3.delete(True)
    if raw_text3 == '/SK':
        CR = credit
    else:
        CR = raw_text3
        
       
    await editable.edit("Now send the **Thumb url**\n**Eg Who's End With .jpg:** ``\n\nor Send `no`")
    input6 = message = await bot.listen(editable.chat.id)
    raw_text6 = input6.text
    await input6.delete(True)
    await editable.delete()

    thumb = input6.text
    if thumb.startswith("http://") or thumb.startswith("https://files.catbox.moe/mwhput.jpg"):
        getstatusoutput(f"wget '{thumb}' -O 'thumb.jpg'")
        thumb = "thumb.jpg"
    else:
        thumb == "no"

    count =int(raw_text)    
    try:
        for i in range(arg-1, len(links)):

            Vxy = links[i][1].replace("file/d/","uc?export=download&id=").replace("www.youtube-nocookie.com/embed", "youtu.be").replace("?modestbranding=1", "").replace("/view?usp=sharing","")
            url = "https://" + Vxy
            if "visionias" in url:
                async with ClientSession() as session:
                    async with session.get(url, headers={'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9', 'Accept-Language': 'en-US,en;q=0.9', 'Cache-Control': 'no-cache', 'Connection': 'keep-alive', 'Pragma': 'no-cache', 'Referer': 'http://www.visionias.in/', 'Sec-Fetch-Dest': 'iframe', 'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Site': 'cross-site', 'Upgrade-Insecure-Requests': '1', 'User-Agent': 'Mozilla/5.0 (Linux; Android 12; RMX2121) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Mobile Safari/537.36', 'sec-ch-ua': '"Chromium";v="107", "Not=A?Brand";v="24"', 'sec-ch-ua-mobile': '?1', 'sec-ch-ua-platform': '"Android"',}) as resp:
                        text = await resp.text()
                        url = re.search(r"(https://.*?playlist.m3u8.*?)\"", text).group(1)

            if "acecwply" in url:
                cmd = f'yt-dlp -o "{name}.%(ext)s" -f "bestvideo[height<={raw_text2}]+bestaudio" --hls-prefer-ffmpeg --no-keep-video --remux-video mkv --no-warning "{url}"'
                

            if "visionias" in url:
                async with ClientSession() as session:
                    async with session.get(url, headers={'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9', 'Accept-Language': 'en-US,en;q=0.9', 'Cache-Control': 'no-cache', 'Connection': 'keep-alive', 'Pragma': 'no-cache', 'Referer': 'http://www.visionias.in/', 'Sec-Fetch-Dest': 'iframe', 'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Site': 'cross-site', 'Upgrade-Insecure-Requests': '1', 'User-Agent': 'Mozilla/5.0 (Linux; Android 12; RMX2121) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Mobile Safari/537.36', 'sec-ch-ua': '"Chromium";v="107", "Not=A?Brand";v="24"', 'sec-ch-ua-mobile': '?1', 'sec-ch-ua-platform': '"Android"',}) as resp:
                        text = await resp.text()
                        url = re.search(r"(https://.*?playlist.m3u8.*?)\"", text).group(1)

            elif 'videos.classplusapp' in url or "tencdn.classplusapp" in url or "webvideos.classplusapp.com" in url or "media-cdn-alisg.classplusapp.com" in url or "videos.classplusapp" in url or "videos.classplusapp.com" in url or "media-cdn-a.classplusapp" in url or "media-cdn.classplusapp" in url:
             url = requests.get(f'https://api.classplusapp.com/cams/uploader/video/jw-signed-url?url={url}', headers={'x-access-token': 'eyJjb3Vyc2VJZCI6IjQ1NjY4NyIsInR1dG9ySWQiOm51bGwsIm9yZ0lkIjo0ODA2MTksImNhdGVnb3J5SWQiOm51bGx9r'}).json()['url']

            elif "apps-s3-jw-prod.utkarshapp.com" in url:
                if 'enc_plain_mp4' in url:
                    url = url.replace(url.split("/")[-1], res+'.mp4')
                    
                elif 'Key-Pair-Id' in url:
                    url = None
                    
                elif '.m3u8' in url:
                    q = ((m3u8.loads(requests.get(url).text)).data['playlists'][1]['uri']).split("/")[0]
                    x = url.split("/")[5]
                    x = url.replace(x, "")
                    url = ((m3u8.loads(requests.get(url).text)).data['playlists'][1]['uri']).replace(q+"/", x)
                    
            elif '/master.mpd' in url:
             vid_id =  url.split("/")[-2]
             url = f"{PWAPI2}?url=https://sec1.pw.live/{vid_id}/master.mpd&quality={raw_text2}"

            name1 = links[i][0].replace("\t", "").replace(":", "").replace("/", "").replace("+", "").replace("#", "").replace("|", "").replace("@", "").replace("*", "").replace(".", "").replace("https", "").replace("http", "").strip()
            name = f'{str(count).zfill(3)}) {name1[:60]} {my_name}'
          

            if "edge.api.brightcove.com" in url:
                bcov = 'bcov_auth=eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJpYXQiOjE3MjQyMzg3OTEsImNvbiI6eyJpc0FkbWluIjpmYWxzZSwiYXVzZXIiOiJVMFZ6TkdGU2NuQlZjR3h5TkZwV09FYzBURGxOZHowOSIsImlkIjoiZEUxbmNuZFBNblJqVEROVmFWTlFWbXhRTkhoS2R6MDkiLCJmaXJzdF9uYW1lIjoiYVcxV05ITjVSemR6Vm10ak1WUlBSRkF5ZVNzM1VUMDkiLCJlbWFpbCI6Ik5Ga3hNVWhxUXpRNFJ6VlhiR0ppWTJoUk0wMVdNR0pVTlU5clJXSkRWbXRMTTBSU2FHRnhURTFTUlQwPSIsInBob25lIjoiVUhVMFZrOWFTbmQ1ZVcwd1pqUTViRzVSYVc5aGR6MDkiLCJhdmF0YXIiOiJLM1ZzY1M4elMwcDBRbmxrYms4M1JEbHZla05pVVQwOSIsInJlZmVycmFsX2NvZGUiOiJOalZFYzBkM1IyNTBSM3B3VUZWbVRtbHFRVXAwVVQwOSIsImRldmljZV90eXBlIjoiYW5kcm9pZCIsImRldmljZV92ZXJzaW9uIjoiUShBbmRyb2lkIDEwLjApIiwiZGV2aWNlX21vZGVsIjoiU2Ftc3VuZyBTTS1TOTE4QiIsInJlbW90ZV9hZGRyIjoiNTQuMjI2LjI1NS4xNjMsIDU0LjIyNi4yNTUuMTYzIn19.snDdd-PbaoC42OUhn5SJaEGxq0VzfdzO49WTmYgTx8ra_Lz66GySZykpd2SxIZCnrKR6-R10F5sUSrKATv1CDk9ruj_ltCjEkcRq8mAqAytDcEBp72-W0Z7DtGi8LdnY7Vd9Kpaf499P-y3-godolS_7ixClcYOnWxe2nSVD5C9c5HkyisrHTvf6NFAuQC_FD3TzByldbPVKK0ag1UnHRavX8MtttjshnRhv5gJs5DQWj4Ir_dkMcJ4JaVZO3z8j0OxVLjnmuaRBujT-1pavsr1CCzjTbAcBvdjUfvzEhObWfA1-Vl5Y4bUgRHhl1U-0hne4-5fF0aouyu71Y6W0eg'
                url = url.split("bcov_auth")[0]+bcov
                
            if "youtu" in url:
                ytf = f"b[height<={raw_text2}][ext=mp4]/bv[height<={raw_text2}][ext=mp4]+ba[ext=m4a]/b[ext=mp4]"
            else:
                ytf = f"b[height<={raw_text2}]/bv[height<={raw_text2}]+ba/b/bv+ba"
            
            if "jw-prod" in url:
                cmd = f'yt-dlp -o "{name}.mp4" "{url}"'

            elif "youtube.com" in url or "youtu.be" in url:
                cmd = f'yt-dlp --cookies youtube_cookies.txt -f "{ytf}" "{url}" -o "{name}".mp4'

            else:
                cmd = f'yt-dlp -f "{ytf}" "{url}" -o "{name}.mp4"'

            try:  
        
                cc = f'**📹 VID_ID: {str(count).zfill(3)}.\n\nTitle: {name1} STUDENTS💛{res}.mkv\n\n📚 Batch Name: {b_name}\n\n📥 Extracted By♠ : {CR}\n\n**👑━━━🩷 𝑻𝒉𝒆 𝑺𝑲 💙━━━👑**'
                cc1 = f'**💾 PDF_ID: {str(count).zfill(3)}.\n\nTitle: {name1} STUDENTS💛.pdf\n\n📚 Batch Name: {b_name}\n\n📥 Extracted By♠ : {CR}\n\n**👑━━━🖤 𝑻𝒉𝒆 𝑺𝑲 🧡━━━👑**'
                    
                
                if "drive" in url:
                    try:
                        ka = await helper.download(url, name)
                        copy = await bot.send_document(chat_id=m.chat.id,document=ka, caption=cc1)
                        count+=1
                        os.remove(ka)
                        time.sleep(1)
                    except FloodWait as e:
                        await m.reply_text(str(e))
                        time.sleep(e.x)
                        continue

                elif ".pdf" in url:
                    try:
                        await asyncio.sleep(4)
        # Replace spaces with %20 in the URL
                        url = url.replace(" ", "%20")
 
        # Create a cloudscraper session
                        scraper = cloudscraper.create_scraper()

        # Send a GET request to download the PDF
                        response = scraper.get(url)

        # Check if the response status is OK
                        if response.status_code == 200:
            # Write the PDF content to a file
                            with open(f'{name}.pdf', 'wb') as file:
                                file.write(response.content)

            # Send the PDF document
                            await asyncio.sleep(4)
                            copy = await bot.send_document(chat_id=m.chat.id, document=f'{name}.pdf', caption=cc1)
                            count += 1

            # Remove the PDF file after sending
                            os.remove(f'{name}.pdf')
                        else:
                            await m.reply_text(f"Failed to download PDF: {response.status_code} {response.reason}")

                    except FloodWait as e:
                        await m.reply_text(str(e))
                        time.sleep(e.x)
                        continue

                elif ".pdf" in url:
                    try:
                        cmd = f'yt-dlp -o "{name}.pdf" "{url}"'
                        download_cmd = f"{cmd} -R 25 --fragment-retries 25"
                        os.system(download_cmd)
                        copy = await bot.send_document(chat_id=m.chat.id, document=f'{name}.pdf', caption=cc1)
                        count += 1
                        os.remove(f'{name}.pdf')
                    except FloodWait as e:
                        await m.reply_text(str(e))
                        time.sleep(e.x)
                        continue                       
                          
                else:
                    Show = f"✰🖥️𝐃𝐨𝐰𝐧𝐥𝐨𝐚𝐝𝐢𝐧𝐠 𝗪𝗮𝗶𝘁..🤖🚀»\n\n📝 Title:- `{name}\n\n🖥️ 𝐐𝐮𝐥𝐢𝐭𝐲 » {raw_text2}`\n\n**🔗 𝐔𝐑𝐋 »** `{url}`\n\n**𝐁𝐨𝐭 𝐌𝐚𝐝𝐞 𝐁𝐲🧸: ✦ @SunilChoudhary08✰"
                    prog = await m.reply_text(Show)
                    res_file = await helper.download_video_fast(url, cmd, name)
                    filename = res_file
                    await prog.delete(True)
                    await helper.send_vid_fast(bot, m, cc, filename, thumb, name, prog)
                    count += 1
                    time.sleep(1)

            except Exception as e:
                await send_failed_notice(bot, m.chat.id, count, name, url, str(e))
                continue

    except Exception as e:
        await m.reply_text(e)
    await m.reply_text("𝐀𝐋𝐋 𝐃𝐎𝐍𝐄 REACTIONS khud doge ya kahna padega .✅🔸")



bot.run()
if __name__ == "__main__":
    asyncio.run(main())
