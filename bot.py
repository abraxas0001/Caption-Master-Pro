import logging
import time
import os
import re
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.error import RetryAfter
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, CallbackQueryHandler
from deep_translator import GoogleTranslator


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
active_sends = {}  # chat_id -> bool (is a send job currently active)
user_language = {}  # chat_id -> language code (default 'en')


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
        "• 🌐 Auto-translate to your language (default: English)\n\n\n"
        "<blockquote>"
        "• 🌐 Global replacements auto-applied (set with /globalreplacement)\n\n"
        "Global Replacement Commands:\n"
        "• /globalreplacement &lt;target&gt; &lt;replacement&gt; — add or update a global replacement\n"
        "• /listglobal — show all global replacements\n"
        "• /removereplacement &lt;index&gt; — remove a global replacement by its list number\n"
        "• /language — change translation language (default: English)\n"
        "• /clear — reset pending media state (cancels current batch and input; does NOT erase global replacements)\n"
        "</blockquote>\n\n"
        "<b>Send your media</b>🎬"
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


def _contains_non_english_non_hindi(text: str) -> bool:
    """Check if text contains non-English alphabets (excluding Hindi/Devanagari).
    Returns True if text has Cyrillic, CJK, Arabic, Thai, Myanmar, etc.
    Returns False for English alphabet or Hindi/Devanagari script.
    """
    if not text:
        return False
    
    # Character ranges for non-English, non-Hindi scripts
    non_english_ranges = [
        (0x0400, 0x04FF),  # Cyrillic
        (0x0530, 0x058F),  # Armenian
        (0x0590, 0x05FF),  # Hebrew
        (0x0600, 0x06FF),  # Arabic
        (0x0700, 0x074F),  # Syriac
        (0x0780, 0x07BF),  # Thaana
        (0x0E00, 0x0E7F),  # Thai
        (0x0E80, 0x0EFF),  # Lao
        (0x1000, 0x109F),  # Myanmar
        (0x10A0, 0x10FF),  # Georgian
        (0x1100, 0x11FF),  # Hangul Jamo
        (0x1200, 0x137F),  # Ethiopic
        (0x13A0, 0x13FF),  # Cherokee
        (0x1400, 0x167F),  # Canadian Aboriginal
        (0x1680, 0x169F),  # Ogham
        (0x16A0, 0x16FF),  # Runic
        (0x1780, 0x17FF),  # Khmer
        (0x1800, 0x18AF),  # Mongolian
        (0x3040, 0x309F),  # Hiragana
        (0x30A0, 0x30FF),  # Katakana
        (0x3100, 0x312F),  # Bopomofo
        (0x3130, 0x318F),  # Hangul Compatibility Jamo
        (0x3400, 0x4DBF),  # CJK Unified Ideographs Extension A
        (0x4E00, 0x9FFF),  # CJK Unified Ideographs
        (0xA000, 0xA48F),  # Yi Syllables
        (0xAC00, 0xD7AF),  # Hangul Syllables
        (0xF900, 0xFAFF),  # CJK Compatibility Ideographs
    ]
    # Devanagari range (Hindi) - we should NOT translate
    devanagari_range = (0x0900, 0x097F)
    
    for char in text:
        code = ord(char)
        # Skip if it's Devanagari (Hindi)
        if devanagari_range[0] <= code <= devanagari_range[1]:
            continue
        # Check if it's in any non-English range
        for start, end in non_english_ranges:
            if start <= code <= end:
                return True
    return False


def _translate_text(text: str, target_lang: str = 'en') -> str:
    """Translate non-English (non-Hindi if target is English) text to target language."""
    if not text:
        return text
    
    # For English target, skip translation if text is already English or Hindi
    if target_lang == 'en' and not _contains_non_english_non_hindi(text):
        return text
    
    try:
        translator = GoogleTranslator(source='auto', target=target_lang)
        translated = translator.translate(text)
        return translated if translated else text
    except Exception as e:
        logger.exception("Translation failed: %s", e)
        return text


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
    except RetryAfter as e:
        # Schedule a retry after Telegram's suggested backoff
        delay = min(10, int(e.retry_after))
        logger.warning("Flood control for Done button; retrying in %s s (capped)", delay)
        try:
            context.job_queue.run_once(show_done_button, delay, context=chat_id)
        except Exception:
            logger.exception("Failed to schedule Done button retry")
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
            InlineKeyboardButton("📄 Use Filename (videos only)", callback_data="mode_filename")
        ],
        [
            InlineKeyboardButton("📝 Filename with Cap (videos only)", callback_data="mode_filename_with_cap"),
            InlineKeyboardButton("🔄 Add Text to Each (videos only)", callback_data="mode_add_to_each")
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
    except RetryAfter as e:
        # Retry showing mode selection after backoff to avoid getting stuck
        delay = min(10, int(e.retry_after))
        logger.warning("Flood control for mode prompt; retrying in %s s (capped)", delay)
        try:
            context.job_queue.run_once(ask_for_mode, delay, context=chat_id)
        except Exception:
            logger.exception("Failed to schedule ask_for_mode retry")
    except Exception as e:
        logger.exception("Failed to ask for mode: %s", e)

    pending_job.pop(chat_id, None)


def button_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    chat_id = query.message.chat_id
    
    # Handle language selection
    if query.data.startswith("lang_"):
        lang_code = query.data.replace("lang_", "")
        user_language[chat_id] = lang_code
        
        lang_names = {
            'en': 'English', 'es': 'Spanish', 'fr': 'French', 'de': 'German',
            'it': 'Italian', 'pt': 'Portuguese', 'ru': 'Russian', 'ja': 'Japanese',
            'ko': 'Korean', 'zh-CN': 'Chinese (Simplified)', 'ar': 'Arabic',
            'hi': 'Hindi', 'tr': 'Turkish', 'nl': 'Dutch', 'pl': 'Polish'
        }
        lang_name = lang_names.get(lang_code, lang_code)
        query.edit_message_text(f"✅ Translation language set to: <b>{lang_name}</b>\n\nAll captions will now be auto-translated to {lang_name}.", parse_mode=ParseMode.HTML)
        return
    
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
    # If filename-based mode, inform how many videos will receive filename captions
    if mode in ("filename", "filename_with_cap", "add_to_each"):
        video_count = sum(1 for t, *_ in items if t == "video")
        other_count = len(items) - video_count
        try:
            if video_count == 0:
                context.bot.send_message(chat_id=chat_id, text="No videos found — keeping original captions for all items.")
            else:
                context.bot.send_message(chat_id=chat_id, text=f"Applying filename-based caption to {video_count} video(s); keeping original captions for {other_count} other items.")
        except Exception:
            # Don't block on this notification
            pass

    # For large batches, send as albums (media groups) to reduce API calls
        if len(items) > 12 and mode not in ("filename", "filename_with_cap", "add_to_each"):
            send_media_as_album(context, chat_id)
            return

    # For filename-based modes we send individually allowing filename application to videos
    if mode in ("filename", "filename_with_cap", "add_to_each"):
        # Use chunked sender that resumes on RetryAfter
        _send_items_with_resume(context, chat_id, items, mode, user_text, batch_size=6)
        return

    for typ, file_id, original_caption, filename in items:
        caption = generate_caption(typ, mode, user_text, original_caption, filename)
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


def _send_items_job(context: CallbackContext):
    data = context.job.context
    chat_id = data['chat_id']
    items = data['items']
    mode = data['mode']
    user_text = data['user_text']
    batch_size = data.get('batch_size', 5)
    _send_items_with_resume(context, chat_id, items, mode, user_text, batch_size)


def _send_items_with_resume(context: CallbackContext, chat_id: int, items: list, mode: str, user_text: str, batch_size: int = 5):
    """Send items in small batches and resume via JobQueue on RetryAfter.
    items: list of tuples (typ, file_id, original_caption, filename)
    """
    if not items:
        # Done sending; clear state
        pending_media.pop(chat_id, None)
        waiting_for_input.pop(chat_id, None)
        return

    to_send = items[:batch_size]
    remaining = items[batch_size:]
    active_sends[chat_id] = True

    for typ, file_id, original_caption, filename in to_send:
        caption = generate_caption(typ, mode, user_text, original_caption, filename)
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
        except RetryAfter as e:
            # Cap retry to 10 seconds to avoid long pauses
            delay = min(10, int(e.retry_after))
            logger.warning("RetryAfter when sending items; scheduling resume in %s seconds (capped)", delay)
            context.job_queue.run_once(_send_items_job, delay, context={'chat_id': chat_id, 'items': remaining, 'mode': mode, 'user_text': user_text, 'batch_size': batch_size})
            return
        except Exception as e:
            logger.exception("Failed to send item: %s", e)
        time.sleep(0.06)

    # If there are remaining items, schedule next chunk immediately with a short delay
    if remaining:
        try:
            context.job_queue.run_once(_send_items_job, 0.2, context={'chat_id': chat_id, 'items': remaining, 'mode': mode, 'user_text': user_text, 'batch_size': batch_size})
        except Exception as e:
            logger.exception("Failed to schedule next send job: %s", e)
    else:
        pending_media.pop(chat_id, None)
        waiting_for_input.pop(chat_id, None)
        active_sends.pop(chat_id, None)


def generate_caption(media_type: str, mode: str, user_text: str, original_caption: str, filename: str) -> str:
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
        # Only apply filename captions for videos; for all other types keep original
        if media_type == "video":
            clean_name = filename.rsplit('.', 1)[0] if '.' in filename else filename
            return clean_name
        return original_caption
    
    elif mode == "filename_with_cap":
        # Only apply to videos; otherwise keep original caption
        if media_type == "video":
            clean_name = filename.rsplit('.', 1)[0] if '.' in filename else filename
            if original_caption:
                return f"{clean_name}\n{original_caption}"
            return clean_name
        return original_caption
    
    elif mode == "add_to_each":
        # Only apply to videos; otherwise keep original caption
        if media_type == "video":
            clean_name = filename.rsplit('.', 1)[0] if '.' in filename else filename
            if user_text:
                return f"{clean_name}\n{user_text}"
            return clean_name
        return original_caption
    
    return ""


def apply_global_replacements(chat_id: int, text: str) -> str:
    if not text:
        return text
    # Apply global text replacements
    pairs = global_replacements.get(chat_id, [])
    for target, repl in pairs:
        if target:
            text = text.replace(target, repl)
    # Auto-translate to user's preferred language (default English)
    target_lang = user_language.get(chat_id, 'en')
    if target_lang != 'en' or _contains_non_english_non_hindi(text):
        text = _translate_text(text, target_lang)
    return text



def language_command(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    current_lang = user_language.get(chat_id, 'en')
    
    lang_names = {
        'en': 'English',
        'es': 'Spanish',
        'fr': 'French',
        'de': 'German',
        'it': 'Italian',
        'pt': 'Portuguese',
        'ru': 'Russian',
        'ja': 'Japanese',
        'ko': 'Korean',
        'zh-CN': 'Chinese (Simplified)',
        'ar': 'Arabic',
        'hi': 'Hindi',
        'tr': 'Turkish',
        'nl': 'Dutch',
        'pl': 'Polish'
    }
    
    current_name = lang_names.get(current_lang, 'English')
    
    keyboard = [
        [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
         InlineKeyboardButton("🇪🇸 Spanish", callback_data="lang_es")],
        [InlineKeyboardButton("🇫🇷 French", callback_data="lang_fr"),
         InlineKeyboardButton("🇩🇪 German", callback_data="lang_de")],
        [InlineKeyboardButton("🇮🇹 Italian", callback_data="lang_it"),
         InlineKeyboardButton("🇵🇹 Portuguese", callback_data="lang_pt")],
        [InlineKeyboardButton("🇷🇺 Russian", callback_data="lang_ru"),
         InlineKeyboardButton("🇯🇵 Japanese", callback_data="lang_ja")],
        [InlineKeyboardButton("🇰🇷 Korean", callback_data="lang_ko"),
         InlineKeyboardButton("🇨🇳 Chinese", callback_data="lang_zh-CN")],
        [InlineKeyboardButton("🇸🇦 Arabic", callback_data="lang_ar"),
         InlineKeyboardButton("🇮🇳 Hindi", callback_data="lang_hi")],
        [InlineKeyboardButton("🇹🇷 Turkish", callback_data="lang_tr"),
         InlineKeyboardButton("🇳🇱 Dutch", callback_data="lang_nl")],
        [InlineKeyboardButton("🇵🇱 Polish", callback_data="lang_pl")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(
        f"🌐 Current translation language: <b>{current_name}</b>\n\n"
        "Captions will be auto-translated to this language.\n"
        "Select a language:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )


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
        "*Translation:*\n"
        "• Auto-translates captions to your language\n"
        "• /language - Change translation language\n\n"
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
    dp.add_handler(CommandHandler("language", language_command))
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
