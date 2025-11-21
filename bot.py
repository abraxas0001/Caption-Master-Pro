import logging
import os
import re
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
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
waiting_for_input = {}  # chat_id -> mode or (mode, step, data)
replace_link_state = {}  # chat_id -> {'target': str, 'replacement': str}
global_replacements = {}  # chat_id -> list of (target, replacement)


def start(update: Update, context: CallbackContext):
    text = (
        "🎯 CaptionxAlbum Bot\n\n"
        "Send media and I'll give you caption options. I can also auto-group into albums.\n\n"
        "✨ Features:\n"
        "• ✏️ New caption\n"
        "• 📋 Keep original\n"
        "• ➕ Append / ⬆️ Prepend\n"
        "• 🔗 Replace links / mentions (two-step)\n"
        "• 📄 Use filename\n"
        "• 📝 Filename with caption\n"
        "• 📚 Make album (groups of 10)\n"
        "• 🌐 Global replacements auto-applied (set with /globalreplacement)\n\n"
        "<blockquote>Global Replacement Commands:\n"
        "• /globalreplacement &lt;target&gt; &lt;replacement&gt; — add or update a global replacement\n"
        "• /listglobal — show all global replacements\n"
        "• /removereplacement &lt;index&gt; — remove a global replacement by its list number\n"
        "• /clear — reset pending media state (cancels current batch and input; does NOT erase global replacements)\n"
        "</blockquote>\n\n"
        "Send your media!"
    )
    update.message.reply_text(text, parse_mode=ParseMode.HTML)


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
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    
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
            InlineKeyboardButton("📝 Filename with Cap", callback_data="mode_filename_with_cap"),
            InlineKeyboardButton("🔄 Add Text to Each", callback_data="mode_add_to_each")
        ],
        [
            InlineKeyboardButton("📚 Make Album", callback_data="mode_make_album")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        from telegram import ReplyKeyboardRemove
        context.bot.send_message(
            chat_id=chat_id,
            text=f"📦 Received {len(items)} media items!\n\nChoose caption mode:",
            reply_markup=ReplyKeyboardRemove()
        )
        context.bot.send_message(
            chat_id=chat_id,
            text="Select mode:",
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
        waiting_for_input[chat_id] = ("replace_links", "target", None)
        query.edit_message_text("🔗 Step 1/2: Send the text/link/mention you want to REPLACE (target)")
    
    elif mode == "add_to_each":
        waiting_for_input[chat_id] = "add_to_each"
        query.edit_message_text("🔄 Send text to add below filename:")
    
    elif mode == "keep":
        query.edit_message_text("📋 Sending with original captions...")
        send_media_with_mode(context, chat_id, "keep", "")
        
    elif mode == "filename":
        query.edit_message_text("📄 Using filenames as captions...")
        send_media_with_mode(context, chat_id, "filename", "")
        
    elif mode == "filename_with_cap":
        query.edit_message_text("📝 Using filename with original caption...")
        send_media_with_mode(context, chat_id, "filename_with_cap", "")
        
    elif mode == "make_album":
        query.edit_message_text("📚 Creating albums (max 10 per group)...")
        send_media_as_album(context, chat_id)
    


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
    
    mode_data = waiting_for_input[chat_id]
    
    # Handle two-step replace_links flow
    if isinstance(mode_data, tuple) and mode_data[0] == "replace_links":
        step = mode_data[1]
        if step == "target":
            # User sent target, now ask for replacement
            waiting_for_input[chat_id] = ("replace_links", "replacement", text)
            update.message.reply_text(f"🔗 Step 2/2: Send what you want to replace '{text}' WITH")
            return
        elif step == "replacement":
            # User sent replacement, process media
            target = mode_data[2]
            replacement = text
            waiting_for_input.pop(chat_id)
            items = pending_media.get(chat_id, [])
            if not items:
                update.message.reply_text("No media found.")
                return
            update.message.reply_text(f"⚡ Processing {len(items)} items...")
            send_media_with_mode(context, chat_id, "replace_links", {"target": target, "replacement": replacement})
            return
    
    
    # Standard single-step flow
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
        caption = apply_global_replacements(chat_id, caption)
        
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


def send_media_as_album(context: CallbackContext, chat_id: int):
    """Send media as albums with max 10 items per group"""
    from telegram import InputMediaPhoto, InputMediaVideo, InputMediaDocument, InputMediaAudio, InputMediaAnimation
    
    items = pending_media.get(chat_id, [])
    if not items:
        return
    
    # Group items into chunks of 10
    chunk_size = 10
    for i in range(0, len(items), chunk_size):
        chunk = items[i:i + chunk_size]
        media_group = []
        
        for typ, file_id, original_caption, filename in chunk:
            caption = original_caption if original_caption else ""
            caption = apply_global_replacements(chat_id, caption)
            
            try:
                if typ == "photo":
                    media_group.append(InputMediaPhoto(media=file_id, caption=caption))
                elif typ == "video":
                    media_group.append(InputMediaVideo(media=file_id, caption=caption))
                elif typ == "document":
                    media_group.append(InputMediaDocument(media=file_id, caption=caption))
                elif typ == "animation":
                    media_group.append(InputMediaAnimation(media=file_id, caption=caption))
                elif typ == "audio":
                    media_group.append(InputMediaAudio(media=file_id, caption=caption))
                # Note: voice messages can't be in media groups, send separately
                elif typ == "voice":
                    context.bot.send_voice(chat_id=chat_id, voice=file_id)
            except Exception as e:
                logger.exception("Failed to prepare media: %s", e)
        
        # Send the media group if we have items
        if media_group:
            try:
                context.bot.send_media_group(chat_id=chat_id, media=media_group)
            except Exception as e:
                logger.exception("Failed to send media group: %s", e)
    
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
        # user_text is now a dict with target and replacement
        if isinstance(user_text, dict):
            target = user_text['target']
            replacement = user_text['replacement']
            if original_caption and target in original_caption:
                return original_caption.replace(target, replacement)
            return original_caption if original_caption else ""
        return original_caption
    
    elif mode == "filename":
        clean_name = filename.rsplit('.', 1)[0] if '.' in filename else filename
        return clean_name
    
    elif mode == "filename_with_cap":
        clean_name = filename.rsplit('.', 1)[0] if '.' in filename else filename
        if original_caption:
            return f"{clean_name}\n{original_caption}"
        return clean_name
    
    elif mode == "add_to_each":
        clean_name = filename.rsplit('.', 1)[0] if '.' in filename else filename
        if user_text:
            return f"{clean_name}\n{user_text}"
        return clean_name
    
    return ""


def apply_global_replacements(chat_id: int, text: str) -> str:
    if not text:
        return text
    pairs = global_replacements.get(chat_id, [])
    for target, repl in pairs:
        if target:
            text = text.replace(target, repl)
    return text



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


def global_replacement_command(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    parts = update.message.text.strip().split(maxsplit=2)
    if len(parts) < 3:
        update.message.reply_text("Usage: /global_replacement <target> <replacement>")
        return
    target = parts[1]
    replacement = parts[2]
    lst = global_replacements.get(chat_id)
    if lst is None:
        lst = []
        global_replacements[chat_id] = lst
    lst[:] = [p for p in lst if p[0] != target]
    lst.append((target, replacement))
    update.message.reply_text(f"✅ Added global replacement: {target} → {replacement}")


def list_global_command(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    pairs = global_replacements.get(chat_id, [])
    if not pairs:
        update.message.reply_text("🌐 No global replacements set.")
        return
    lines = ["🌐 Global replacements:"]
    for idx, (t, r) in enumerate(pairs, start=1):
        lines.append(f"{idx}. {t} → {r}")
    update.message.reply_text("\n".join(lines))


def remove_replacement_command(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    parts = update.message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        update.message.reply_text("Usage: /remove_replacement <index>")
        return
    try:
        idx = int(parts[1])
    except ValueError:
        update.message.reply_text("Index must be a number.")
        return
    pairs = global_replacements.get(chat_id, [])
    if idx < 1 or idx > len(pairs):
        update.message.reply_text("Invalid index.")
        return
    removed = pairs.pop(idx - 1)
    update.message.reply_text(f"✅ Removed: {removed[0]} → {removed[1]}")


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
        "• Replace Links/Mentions (2-step)\n"
        "• Use Filename\n"
        "• Filename with Caption\n\n"
        "*Albums:*\n" 
        "• 📚 Make Album groups media (max 10 items each)\n\n"
        "*Global Replacements:*\n"
        "• /global_replacement <target> <replacement>\n"
        "• /list_global\n"
        "• /remove_replacement <index>\n\n"
        "/clear - Reset",
        parse_mode='Markdown'
    )


def main():
    updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_command))
    dp.add_handler(CommandHandler("clear", clear_command))
    dp.add_handler(CommandHandler("global_replacement", global_replacement_command))
    dp.add_handler(CommandHandler("list_global", list_global_command))
    dp.add_handler(CommandHandler("remove_replacement", remove_replacement_command))
    
    dp.add_handler(CallbackQueryHandler(button_callback))

    media_filter = Filters.photo | Filters.video | Filters.document | Filters.animation | Filters.audio | Filters.voice
    dp.add_handler(MessageHandler(media_filter, save_media))

    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text))

    updater.start_polling()
    logger.info("Bot started")
    updater.idle()


if __name__ == '__main__':
    main()
