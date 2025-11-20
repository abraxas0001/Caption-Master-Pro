# 🎯 Caption-Master-Pro

Advanced Telegram bot for flexible bulk caption editing. Send media, wait 2 seconds, click Done, pick a mode, and the bot returns everything with modified captions.

## ✨ Features

### Caption Modes

1. **✏️ New Caption** - Replace all captions with a single new caption
2. **📋 Keep Original** - Keep existing captions unchanged
3. **➕ Append Text** - Add text at the end of existing captions
4. **⬆️ Prepend Text** - Add text at the beginning of existing captions
5. **🔗 Replace Links** - Find and replace all URLs in captions with your link
6. **📄 Use Filename** - Use the original filename as caption
7. **🚫 Remove Caption** - Send media without any caption
8. **🔄 Add Text to Each** - Add text to each media (appends if caption exists)

### Smart Features

- Preserves original captions and filenames
- Handles photos, videos, documents, animations, audio files
- Interactive button-based UI
- Works with albums and individual media
- Intelligent link detection and replacement
- Clean filename extraction (removes extensions)

## Setup

1. Create a bot and get the token from @BotFather.
2. Copy the token into a `.env` file at the project root with the variable `TELEGRAM_BOT_TOKEN`:

```
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
```

3. (Optional) Use a venv, then install dependencies:

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r "requirements.txt"
```

## Run

```powershell
python bot.py
```

## How to Use

1. **Start the bot** - Send `/start` to see welcome message
2. **Send media** - Upload one or multiple media files (can be albums or individual)
3. **Wait 2 seconds** - Bot detects when you're done sending
4. **Choose mode** - Select from 8 caption modes via button menu
5. **Follow prompts** - Some modes ask for text/link input
6. **Receive media** - Get all media back with your caption modifications

## Commands

- `/start` - Start the bot and see welcome message
- `/help` - Show detailed help with all features
- `/clear` - Clear pending media and start over

## Usage Examples

### Replace Links in Media
- Send media with captions containing URLs
- Choose "🔗 Replace Links"
- Send your new link
- All URLs in original captions are replaced

### Append Text to Existing Captions
- Send media with existing captions
- Choose "➕ Append Text"
- Type your additional text
- Original caption + your text on each media

### Use Filenames as Captions
- Send documents/videos with filenames
- Choose "📄 Use Filename"
- Filename becomes the caption (extension removed)

### Add Same Text to All
- Send multiple media (with or without captions)
- Choose "🔄 Add Text to Each"
- Type your text
- Appends to existing or creates new caption

## Notes

- The bot sends each media back individually to ensure captions are properly applied
- Original captions and filenames are preserved during collection
- URL detection uses regex pattern to find and replace links
- Voice messages cannot have captions (Telegram limitation)
- Bot state is per-chat, so multiple users can use simultaneously
- Use `/clear` command to cancel current operation and start fresh

## Advanced Use Cases

**Scenario: Media with links that you want to replace**
1. Forward/send media from another source with promotional links
2. Choose "Replace Links" mode
3. Enter your affiliate/tracking link
4. All original links are replaced with yours

**Scenario: Want to add your branding to all media**
1. Collect media from various sources
2. Choose "Add Text to Each" mode  
3. Enter your watermark text or channel link
4. Each media gets your branding appended

**Scenario: Clean up filenames for presentation**
1. Send documents with messy filenames
2. Choose "Use Filename" mode
3. Get clean captions from filenames (no extensions)

