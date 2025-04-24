import os
import time
import asyncio
from math import ceil
import logging
import ffmpeg
from info import DUMP_CHANNEL, LOG_CHANNEL
from database.db import db
from utils import split_video
from plugins.progress_bar import progress_for_pyrogram


async def upload_media(client, chat_id, output_filename, caption, duration, width, height, status_msg, thumbnail_path, link):
    if output_filename and os.path.exists(output_filename):
        logging.info(output_filename)
        await status_msg.edit_text("📤 **Uploading media...**")
        start_time = time.time()

        async def upload_progress(sent, total):
            await progress_for_pyrogram(sent, total, "📤 **Uploading...**", status_msg, start_time)

        try:
            # Fetch user settings
            user_settings = await db.get_user_settings(chat_id)
            upload_as_doc = user_settings.get("upload_as_doc", False)

            split_files = await split_video(output_filename)
            total_parts = len(split_files)
            user = await client.get_users(chat_id)
            mention_user = f"[{user.first_name}](tg://user?id={user.id})"

            for idx, part_file in enumerate(split_files, start=1):
                part_caption = f"**{caption}**\n**Part {idx}/{total_parts}**" if total_parts > 1 else f"**{caption}**"
                
                with open(part_file, "rb") as media_file:
                    if upload_as_doc:
                        sent_message = await client.send_document(
                            chat_id=chat_id,
                            document=media_file,
                            caption=part_caption,
                            progress=upload_progress,
                            disable_notification=True,
                            thumb=thumbnail_path if thumbnail_path else None,
                            file_name=os.path.basename(part_file)
                        )
                    else:
                        if part_file.endswith('.mp4') or part_file.endswith('.mkv'):
                            sent_message = await client.send_video(
                                chat_id=chat_id,
                                video=media_file,
                                progress=upload_progress,
                                caption=part_caption,
                                duration=duration // total_parts if total_parts > 1 else duration,
                                supports_streaming=True,
                                height=height,
                                width=width,
                                disable_notification=True,
                                thumb=thumbnail_path if thumbnail_path else None,
                                file_name=os.path.basename(part_file)
                            )
                        elif part_file.endswith('.mp3') or part_file.endswith('.wav'):
                            sent_message = await client.send_audio(
                                chat_id=chat_id,
                                audio=media_file,
                                progress=upload_progress,
                                caption=part_caption,
                                duration=duration // total_parts if total_parts > 1 else duration,
                                disable_notification=True,
                                thumb=thumbnail_path if thumbnail_path else None,
                                file_name=os.path.basename(part_file)
                            )

                # Extract file_id
                if hasattr(sent_message, 'video') and sent_message.video:
                    file_id = sent_message.video.file_id
                elif hasattr(sent_message, 'audio') and sent_message.audio:
                    file_id = sent_message.audio.file_id
                elif hasattr(sent_message, 'document') and sent_message.document:
                    file_id = sent_message.document.file_id
                else:
                    logging.error("No valid file_id found in sent_message.")
                    file_id = None

                # Upload to dump channel
                if file_id:
                    formatted_caption = (
                        f"{part_caption}\n\n"
                        f"✅ **Dᴏᴡɴʟᴏᴀᴅᴇᴅ Bʏ: {mention_user}**\n"
                        f"📌 **Sᴏᴜʀᴄᴇ URL: [Click Here]({link})**"
                    )

                    if upload_as_doc:
                        await client.send_document(
                            chat_id=DUMP_CHANNEL,
                            document=file_id,
                            caption=formatted_caption,
                            disable_notification=True,
                            thumb=thumbnail_path if thumbnail_path else None,
                            file_name=os.path.basename(part_file)
                        )
                    else:
                        if part_file.endswith('.mp4') or part_file.endswith('.mkv'):
                            await client.send_video(
                                chat_id=DUMP_CHANNEL,
                                video=file_id,
                                caption=formatted_caption,
                                duration=duration // total_parts if total_parts > 1 else duration,
                                supports_streaming=True,
                                height=height,
                                width=width,
                                disable_notification=True,
                                thumb=thumbnail_path if thumbnail_path else None,
                                file_name=os.path.basename(part_file)
                            )
                        elif part_file.endswith('.mp3') or part_file.endswith('.wav'):
                            await client.send_audio(
                                chat_id=DUMP_CHANNEL,
                                audio=file_id,
                                caption=formatted_caption,
                                duration=duration // total_parts if total_parts > 1 else duration,
                                disable_notification=True,
                                thumb=thumbnail_path if thumbnail_path else None,
                                file_name=os.path.basename(part_file)
                            )

                    os.remove(part_file)

            await status_msg.edit_text("✅ **Upload Successful!**")
            await db.increment_task(chat_id)
            await db.increment_download_count()
            await status_msg.delete()

        except Exception as e:
            user = await client.get_users(chat_id)
            error_report = (
                f"❌ **Upload Failed!**\n\n"
                f"**User:** [{user.first_name}](tg://user?id={user.id}) (`{user.id}`)\n"
                f"**Filename:** `{output_filename}`\n"
                f"**Source:** [Link]({link})\n"
                f"**Error:** `{str(e)}`"
            )
            await client.send_message(LOG_CHANNEL, error_report)
            await status_msg.edit_text("❌ **Oops! Something went wrong during upload.**")

        finally:
            if os.path.exists(output_filename):
                os.remove(output_filename)
            if thumbnail_path and os.path.exists(thumbnail_path):
                os.remove(thumbnail_path)

    else:
        try:
            user = await client.get_users(chat_id)
            error_report = (
                f"❌ **Upload Failed - File Not Found!**\n\n"
                f"**User:** [{user.first_name}](tg://user?id={user.id}) (`{user.id}`)\n"
                f"**Expected File:** `{output_filename}`\n"
                f"**Source:** [YouTube Link]({link})"
            )
            await client.send_message(LOG_CHANNEL, error_report)
        except Exception as e:
            await client.send_message(LOG_CHANNEL, f"❌ Error while logging failed upload:\n`{str(e)}`")

        await status_msg.edit_text("❌ **Oops! Upload failed. Please try again later.**")
