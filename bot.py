import logging
import os
import re
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, CallbackQueryHandler


load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    print("Error: set TELEGRAM_BOT_TOKEN in environment or .env file")
    raise SystemExit(1)


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)


# In-memory per-chat state
pending_media = {}  # chat_id -> list of (type, file_id, original_caption, filename)
pending_job = {}  # chat_id -> Job
waiting_for_input = {}  # chat_id -> mode


def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "🎯 *Caption Bot*\n\n"
        "Send media and I'll give you caption options:\n\n"
        "✨ Features:\n"
        "• New caption\n"
        "• Keep original\n"
        "• Append/Prepend text\n"
        "• Replace links (FIXED!)\n"
        "• Use filename\n"
        "• Remove caption\n\n"
        "Send your media!",
        parse_mode='Markdown'
    )


def _append_media(chat_id, media_item):
    lst = pending_media.get(chat_id)
    if lst is None:
        lst = []
        pending_media[chat_id] = lst
    lst.append(media_item)


def _get_filename(msg, media_type):
    try:
        if media_type == "photo":
            return f"photo_{msg.photo[-1].file_unique_id}.jpg"
        elif media_type == "video":
            return msg.video.file_name or f"video_{msg.video.file_unique_id}.mp4"
        elif media_type == "document":
            return msg.document.file_name or f"document_{msg.document.file_unique_id}"
        elif media_type == "animation":
            return msg.animation.file_name or f"animation_{msg.animation.file_unique_id}.gif"
        elif media_type == "audio":
            return msg.audio.file_name or f"audio_{msg.audio.file_unique_id}.mp3"
        elif media_type == "voice":
            return f"voice_{msg.voice.file_unique_id}.ogg"
    except Exception:
        return "unknown_file"


def save_media(update: Update, context: CallbackContext):
    msg = update.message
    chat_id = msg.chat_id
    original_caption = msg.caption or ""

    media_type = None
    file_id = None
    
    if msg.photo:
        media_type = "photo"
        file_id = msg.photo[-1].file_id
    elif msg.video:
        media_type = "video"
        file_id = msg.video.file_id
    elif msg.document:
        media_type = "document"
        file_id = msg.document.file_id
    elif msg.animation:
        media_type = "animation"
        file_id = msg.animation.file_id
    elif msg.audio:
        media_type = "audio"
        file_id = msg.audio.file_id
    elif msg.voice:
        media_type = "voice"
        file_id = msg.voice.file_id
    else:
        return

    filename = _get_filename(msg, media_type)
    _append_media(chat_id, (media_type, file_id, original_caption, filename))

    # Cancel any existing job
    job = pending_job.get(chat_id)
    if job:
        try:
            job.schedule_removal()
        except Exception:
            pass

    # Schedule notification after 2 seconds of no new media
    job = context.job_queue.run_once(show_done_button, 2.0, context=chat_id)
    pending_job[chat_id] = job


def show_done_button(context: CallbackContext):
    """Show Done button after 2 seconds of no new media"""
    chat_id = context.job.context
    items = pending_media.get(chat_id, [])
    
    if not items:
        return
    
    from telegram import KeyboardButton, ReplyKeyboardMarkup
    keyboard = [[KeyboardButton("✅ Done")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    
    try:
        context.bot.send_message(
            chat_id=chat_id,
            text=f"📦 Received {len(items)} media. Send more or click Done.",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.exception("Failed to show done button: %s", e)
    
    pending_job.pop(chat_id, None)


def ask_for_mode(context: CallbackContext, chat_id: int = None):
    # Support being called from job or directly
    if chat_id is None:
        chat_id = context.job.context
    
    items = pending_media.get(chat_id, [])
    if not items:
        return

    keyboard = [
        [
            InlineKeyboardButton("✏️ New Caption", callback_data="mode_new"),
            InlineKeyboardButton("📋 Keep Original", callback_data="mode_keep")
        ],
        [
            InlineKeyboardButton("➕ Append Text", callback_data="mode_append"),
            InlineKeyboardButton("⬆️ Prepend Text", callback_data="mode_prepend")
        ],
        [
            InlineKeyboardButton("🔗 Replace Links", callback_data="mode_replace_links"),
            InlineKeyboardButton("📄 Use Filename", callback_data="mode_filename")
        ],
        [
            InlineKeyboardButton("🚫 Remove Caption", callback_data="mode_remove"),
            InlineKeyboardButton("🔄 Add Text to Each", callback_data="mode_add_to_each")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        from telegram import ReplyKeyboardRemove
        context.bot.send_message(
            chat_id=chat_id,
            text=f"📦 Received {len(items)} media items!\n\nChoose caption mode:",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.exception("Failed to ask for mode: %s", e)

    pending_job.pop(chat_id, None)


def button_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    chat_id = query.message.chat_id
    mode = query.data.replace("mode_", "")
    
    items = pending_media.get(chat_id, [])
    if not items:
        query.edit_message_text("No media found.")
        return

    if mode == "new":
        waiting_for_input[chat_id] = "new"
        query.edit_message_text("✏️ Send the new caption:")
        
    elif mode == "append":
        waiting_for_input[chat_id] = "append"
        query.edit_message_text("➕ Send text to append:")
        
    elif mode == "prepend":
        waiting_for_input[chat_id] = "prepend"
        query.edit_message_text("⬆️ Send text to prepend:")
        
    elif mode == "replace_links":
        waiting_for_input[chat_id] = "replace_links"
        query.edit_message_text("🔗 Send your new link:")
    
    elif mode == "add_to_each":
        waiting_for_input[chat_id] = "add_to_each"
        query.edit_message_text("🔄 Send text to add below filename:")
    
    elif mode == "keep":
        query.edit_message_text("📋 Sending with original captions...")
        send_media_with_mode(context, chat_id, "keep", "")
        
    elif mode == "filename":
        query.edit_message_text("📄 Using filenames as captions...")
        send_media_with_mode(context, chat_id, "filename", "")
        
    elif mode == "remove":
        query.edit_message_text("🚫 Removing captions...")
        send_media_with_mode(context, chat_id, "remove", "")


def handle_text(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    text = update.message.text or ""
    
    # Check if user clicked Done button
    if text == "✅ Done":
        items = pending_media.get(chat_id, [])
        if items:
            # Call ask_for_mode directly with chat_id
            ask_for_mode(context, chat_id)
        else:
            update.message.reply_text("No media found. Send media first.")
        return
    
    if chat_id not in waiting_for_input:
        return
    
    mode = waiting_for_input.pop(chat_id)
    
    items = pending_media.get(chat_id, [])
    if not items:
        update.message.reply_text("No media found.")
        return
    
    update.message.reply_text(f"⚡ Processing {len(items)} items...")
    send_media_with_mode(context, chat_id, mode, text)


def send_media_with_mode(context: CallbackContext, chat_id: int, mode: str, user_text: str):
    items = pending_media.get(chat_id, [])
    
    for typ, file_id, original_caption, filename in items:
        caption = generate_caption(mode, user_text, original_caption, filename)
        
        try:
            if typ == "photo":
                context.bot.send_photo(chat_id=chat_id, photo=file_id, caption=caption)
            elif typ == "video":
                context.bot.send_video(chat_id=chat_id, video=file_id, caption=caption)
            elif typ == "document":
                context.bot.send_document(chat_id=chat_id, document=file_id, caption=caption)
            elif typ == "animation":
                context.bot.send_animation(chat_id=chat_id, animation=file_id, caption=caption)
            elif typ == "audio":
                context.bot.send_audio(chat_id=chat_id, audio=file_id, caption=caption)
            elif typ == "voice":
                context.bot.send_voice(chat_id=chat_id, voice=file_id)
        except Exception as e:
            logger.exception("Failed to send: %s", e)
    
    pending_media.pop(chat_id, None)
    waiting_for_input.pop(chat_id, None)


def generate_caption(mode: str, user_text: str, original_caption: str, filename: str) -> str:
    if mode == "new":
        return user_text
    
    elif mode == "keep":
        return original_caption
    
    elif mode == "append":
        if original_caption:
            return f"{original_caption}\n{user_text}"
        return user_text
    
    elif mode == "prepend":
        if original_caption:
            return f"{user_text}\n{original_caption}"
        return user_text
    
    elif mode == "replace_links":
        # Replace every URL with the new link; append if none matched
        url_pattern = r'https?://\S+'
        if original_caption:
            new_caption = re.sub(url_pattern, user_text, original_caption)
            if new_caption == original_caption:
                # No URLs found; append link
                return f"{original_caption}\n{user_text}" if original_caption else user_text
            return new_caption
        return user_text
    
    elif mode == "filename":
        clean_name = filename.rsplit('.', 1)[0] if '.' in filename else filename
        return clean_name
    
    elif mode == "remove":
        return ""
    
    elif mode == "add_to_each":
        clean_name = filename.rsplit('.', 1)[0] if '.' in filename else filename
        if user_text:
            return f"{clean_name}\n{user_text}"
        return clean_name
    
    return ""


def clear_command(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    
    job = pending_job.get(chat_id)
    if job:
        try:
            job.schedule_removal()
        except Exception:
            pass
    
    pending_media.pop(chat_id, None)
    pending_job.pop(chat_id, None)
    waiting_for_input.pop(chat_id, None)
    
    update.message.reply_text("Cleared!")


def help_command(update: Update, context: CallbackContext):
    update.message.reply_text(
        "*Caption Bot Help*\n\n"
        "1. Send media\n"
        "2. Wait 2 seconds\n"
        "3. Choose mode\n"
        "4. Get media back\n\n"
        "*Modes:*\n"
        "• New Caption\n"
        "• Keep Original\n"
        "• Append/Prepend\n"
        "• Replace Links (fixed!)\n"
        "• Use Filename\n"
        "• Remove\n\n"
        "/clear - Reset",
        parse_mode='Markdown'
    )


def main():
    updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_command))
    dp.add_handler(CommandHandler("clear", clear_command))
    
    dp.add_handler(CallbackQueryHandler(button_callback))

    media_filter = Filters.photo | Filters.video | Filters.document | Filters.animation | Filters.audio | Filters.voice
    dp.add_handler(MessageHandler(media_filter, save_media))

    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text))

    updater.start_polling()
    logger.info("Bot started")
    updater.idle()


if __name__ == '__main__':
    main()
