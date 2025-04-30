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
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ForceReply
from googleapiclient.discovery import build
from plugins.download import download_video, aria2c_media, google_drive

# Configure Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Directories
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

async def is_direct_download_link(url: str) -> bool:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.head(url, timeout=5) as resp:
                content_type = resp.headers.get("Content-Type", "")
                return any(x in content_type for x in ["video/", "audio/", "application/"])
    except:
        return False
        
async def get_terabox_info(link):
    api_url = f"https://teraboxdl-sjjs-projects.vercel.app/api?link={link}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as response:
                if response.status != 200:
                    return {"error": f"HTTP {response.status}"}
                data = await response.json()

        info = data.get("Extracted Info", [])[0] if data.get("Extracted Info") else None
        if not info:
            return {"error": "No extracted info found."}

        return {
            "title": info.get("Title"),
            "size": info.get("Size"),
            "download_url": info.get("Direct Download Link")
        }

    except Exception as e:
        return {"error": str(e)}

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
    
async def is_supported_by_ytdlp(url):
     try:
         cmd = ["yt-dlp", "--quiet", "--simulate", url]
         result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
 
         return result.returncode == 0
     except Exception:
         return False

def clean_filename(filename, mime=None):
    name, ext = os.path.splitext(filename)
    if not ext or ext == '':
        if mime:
            guessed_ext = mimetypes.guess_extension(mime)
            ext = guessed_ext if guessed_ext else '.mkv'
        else:
            ext = '.mkv'
    name = re.sub(r'[^\w\s-]', '', name)
    name = re.sub(r'[-\s]+', '_', name)
    name = name.strip('_')

    return name + ext



@Client.on_message(filters.private & filters.text)
async def universal_handler(client, message):
    text = message.text.strip()
    if not text.startswith("http"):
        return

    chat_id = message.chat.id
    checking_msg = await message.reply_text("🔎 Checking your link, please wait...")

    try:
        # Google Drive
        if "drive.google.com" in text:
            file_id = extract_file_id(text)
            if not file_id:
                await checking_msg.edit("❌ Invalid Google Drive link.")
                return
                
            name, size, mime = get_file_info(file_id)
 
            await checking_msg.edit(f"✅ Processing Google Drive link...")
            await google_drive(client, chat_id, text, name)

        # TeraBox
        elif "terabox.com" in text:
            await checking_msg.edit("✅ Processing TeraBox link...")
            terabox_info = await get_terabox_info(text)
            logging.info(terabox_info)
            if "error" in terabox_info:
                await checking_msg.edit("❌ Invalid TeraBox link.")
                return
                
            dwn = terabox_info.get("download_url")
            await aria2c_media(client, chat_id, dwn)

        # Direct download link (check HEAD)
        elif await is_direct_download_link(text):
            await checking_msg.edit("✅ Direct download link detected. Starting download...")
            await aria2c_media(client, chat_id, text)

        # yt-dlp supported
        elif await is_supported_by_ytdlp(text):
            await checking_msg.edit("✅ Processing video link...")
            await download_video(client, chat_id, text)

        # Unsupported
        else:
            await checking_msg.edit("❌ Unsupported or invalid link format.")

    except Exception as e:
        logger.error(f"Error: {e}")
        await checking_msg.edit("❌ THis to process link.")
