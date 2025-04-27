import sys
import os
import asyncio
import re
import mimetypes
import pickle
import subprocess
import logging
import aiohttp
import yt_dlp

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from googleapiclient.discovery import build
from plugins.download import download_video, aria2c_media, google_drive

# Configure Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Directories
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Memory stores
memory_store = {}
rename_store = {}

# ========== Utility Functions ==========


@Client.on_message(filters.private & filters.reply)
async def rename_handscler(client, message):
    if message.reply_to_message:
        logger.info(f"Reply message: {message.reply_to_message.text}")
    else:
        logger.info("Message is not a reply.")


def extract_file_id(link):
    patterns = [
        r'/file/d/([a-zA-Z0-9_-]+)',
        r'id=([a-zA-Z0-9_-]+)'
    ]
    for pattern in patterns:
        match = re.search(pattern, link)
        if match:
            return match.group(1)
    return None

def get_file_info(file_id):
    creds = pickle.load(open("/app/plugins/token.pickle", "rb"))
    service = build("drive", "v3", credentials=creds)
    file = service.files().get(fileId=file_id, fields="name, size, mimeType").execute()
    name = file.get("name")
    size = int(file.get("size", 0))
    mime = file.get("mimeType")
    return name, size, mime

def human_readable_size(size_bytes):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} PB"

def clean_filename(filename, mime=None):
    name, ext = os.path.splitext(filename)
    if not ext or ext == '':
        if mime:
            guessed_ext = mimetypes.guess_extension(mime)
            ext = guessed_ext if guessed_ext else '.mkv'
        else:
            ext = '.mkv'

    # Clean name
    name = re.sub(r'[^\w\s-]', '', name)
    name = re.sub(r'[-\s]+', '_', name)
    name = name.strip('_')

    return name + ext

async def get_direct_file_info(url):
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.head(url, allow_redirects=True) as response:
                if response.status != 200:
                    raise Exception(f"Failed to fetch file info. Status code: {response.status}")

                headers = response.headers
                filename = None
                if 'Content-Disposition' in headers:
                    dispo = headers['Content-Disposition']
                    filename_match = re.search(r'filename="?([^"]+)"?', dispo)
                    if filename_match:
                        filename = filename_match.group(1)

                size = int(headers.get('Content-Length', 0))
                mime = headers.get('Content-Type', None)

                if not filename:
                    filename = "downloaded_file"

                return filename, size, mime

    except asyncio.TimeoutError:
        raise Exception("Timeout exceeded while fetching file info.")
    except Exception as e:
        raise Exception(f"Error: {str(e)}")

async def is_supported_by_ytdlp(url):
    try:
        cmd = ["yt-dlp", "--quiet", "--simulate", url]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        return result.returncode == 0
    except Exception:
        return False

async def get_ytdlp_info(url):
    ydl_opts = {
        'quiet': True,
        'skip_download': True,
        'noplaylist': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        title = info.get('title', 'unknown_file')
        filesize = info.get('filesize') or info.get('filesize_approx') or 0
        ext = info.get('ext', 'mp4')
        mime = f"video/{ext}"

    return title, filesize, mime

# ========== Main Handler ==========

@Client.on_message(filters.private & filters.text)
async def universal_handler(client, message):
    text = message.text.strip()

    if not text.startswith("http"):
        return

    chat_id = message.chat.id
    random_id = str(chat_id) + "_" + str(message.id)

    if "drive.google.com" in text:
        await message.reply("📥 Google Drive link detected! Fetching file details...")

        file_id = extract_file_id(text)
        if not file_id:
            return await message.reply("❌ Invalid Google Drive link.")

        try:
            name, size, mime = get_file_info(file_id)
            size_str = human_readable_size(size)
            clean_name = clean_filename(name, mime)

            memory_store[random_id] = {
                'link': text,
                'filename': clean_name,
                'source': 'gdrive'
            }

            buttons = InlineKeyboardMarkup([ 
                [InlineKeyboardButton("✅ Default Name", callback_data=f"default_{random_id}")],
                [InlineKeyboardButton("✏️ Rename", callback_data=f"rename_{random_id}")]
            ])

            await message.reply(
                f"📄 **File Name:** `{clean_name}`\n📦 **Size:** `{size_str}`\n🧾 **MIME Type:** `{mime}`",
                reply_markup=buttons
            )

        except Exception as e:
            await message.reply(f"❌ Error: {e}")

    else:
        await message.reply("📥 Checking link type...")

        try:
            if await is_supported_by_ytdlp(text):
                await message.reply("🔗 Supported by yt-dlp! Fetching details...")

                name, size, mime = await get_ytdlp_info(text)
                size_str = human_readable_size(size)
                clean_name = clean_filename(name, mime)

                memory_store[random_id] = {
                    'link': text,
                    'filename': clean_name,
                    'source': 'yt-dlp'
                }

            else:
                await message.reply("🔗 Direct link detected! Fetching details...")

                name, size, mime = await get_direct_file_info(text)
                size_str = human_readable_size(size)
                clean_name = clean_filename(name, mime)

                memory_store[random_id] = {
                    'link': text,
                    'filename': clean_name,
                    'source': 'direct'
                }

            buttons = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Default Name", callback_data=f"default_{random_id}")],
                [InlineKeyboardButton(" Rename", callback_data=f"rename_{random_id}")]
            ])

            await message.reply(
                f"📄 **File Name:** `{clean_name}`\n📦 **Size:** `{size_str}`\n🧾 **MIME Type:** `{mime}`",
                reply_markup=buttons
            )

        except Exception as e:
            await message.reply(f"❌ Error: {e}")

# ========== Callback Query Handler ==========
# ========== Callback Query Handler ==========

@Client.on_callback_query()
async def button_handler(client, callback_query):
    data = callback_query.data
    chat_id = callback_query.message.chat.id

    if data.startswith("default_"):
        random_id = data.split("_", 1)[1]
        await callback_query.message.delete()

        if random_id in memory_store:
            entry = memory_store.pop(random_id)
            await start_download(client, chat_id, entry['link'], entry['filename'], entry['source'])

    elif data.startswith("rename_"):
        random_id = data.split("_", 1)[1]
        await callback_query.message.edit("✏️ Send me the new filename (including the extension). Reply to this message with the new filename.")

        if random_id in memory_store:
            rename_store[chat_id] = random_id  # Store the random_id with the chat_id

# ========== Rename Message Handler ==========

@Client.on_message(filters.private & filters.reply)
async def renamegjgujgjfy_handler(client, message):
    logger.info(f"Received message from chat {message.chat.id}, text: {message.text}")
    logger.info(f"Message is reply? {message.reply_to_message is not None}")

    if message.reply_to_message and message.reply_to_message.text == "✏️ Send me the new filename (including the extension). Reply to this message with the new filename.":
        chat_id = message.chat.id
        logger.info(f"User is replying to the correct prompt: {chat_id}")

        if chat_id in rename_store:
            random_id = rename_store.pop(chat_id)
            new_filename = message.text.strip()

            logger.info(f"Received new filename: {new_filename} for random_id: {random_id}")

            memory_store[random_id]['filename'] = new_filename

            await message.reply(f"✅ Filename changed to `{new_filename}`\n\nStarting download...")

            entry = memory_store.pop(random_id)
            await start_download(client, chat_id, entry['link'], new_filename, entry['source'])
        else:
            await message.reply("❌ You need to press 'Rename' first to change the filename.")
    else:
        logger.info(f"Message is not a valid reply: {message.text}")
        await message.reply("❌ You need to reply to the 'Rename' prompt with the new filename.")


# ========== Download Starter ==========

async def start_download(client, chat_id, link, filename, source):
    try:
        if source == "gdrive":
            await google_drive(client, chat_id, filename, link)
        elif source == "yt-dlp":
            await download_video(client, chat_id, link)
        elif source == "direct":
            await aria2c_media(client, chat_id, link, filename)
    except Exception as e:
        await client.send_message(chat_id, f"❌ Download Error: {e}")
