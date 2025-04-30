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

async def is_supported_by_ytdlp(url):
     try:
         cmd = ["yt-dlp", "--quiet", "--simulate", url]
         result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
 
         return result.returncode == 0
     except Exception:
         return False
 

@Client.on_message(filters.private & filters.text)
async def universal_handler(client, message):
    text = message.text.strip()
    if not text.startswith("http"):
        return

    chat_id = message.chat.id
    checking_msg = await message.reply_text("🔎 Checking your link, please wait...")

    try:
        if "drive.google.com" in text:
            file_id = extract_file_id(text)
            if not file_id:
                await checking_msg.edit("❌ Invalid Google Drive link.")
                return

            await checking_msg.edit("✅ Processing Google Drive link...")
            await google_drive(client, chat_id, text)

        elif "terabox.com" in text:
            await checking_msg.edit("✅ Processing TeraBox link...")
            terabox_info = await get_terabox_info(text)
            logging.info(terabox_info)
            if "error" in terabox_info:
                await checking_msg.edit(f"thsi not link")
                return
                
            dwn = terabox_info.get("download_url")
            await aria2c_media(client, chat_id, dwn)

        elif await is_supported_by_ytdlp(text):
            await checking_msg.edit("✅ Processing video link...")
            await download_video(client, chat_id, text)

        else:
            await aria2c_media(client, chat_id, text)

    except Exception as e:
        logger.error(f"Error: {e}")
        await checking_msg.edit("❌ Failed to process link.")

        await client.send_message(chat_id, f"❌ Download Error: {e}")
        logger.error(f"Download failed for {link}: {str(e)}")
