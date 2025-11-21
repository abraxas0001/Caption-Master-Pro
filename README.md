# 🎯 Caption-Master-Pro

Advanced Telegram bot for flexible bulk caption editing. Send media, wait 2 seconds, click Done, pick a mode, and the bot returns everything with modified captions.

## ✨ Features

### Caption Modes

1. **✏️ New Caption** - Replace all captions with a single new caption.
2. **📋 Keep Original** - Keep existing captions unchanged.
3. **➕ Append Text** - Add text at the end of existing captions.
4. **⬆️ Prepend Text** - Add text at the beginning of existing captions.
5. **🔗 Replace Links** - Two-step: first send the target link/text you want to replace, then the replacement. All matches replaced across captions.
6. **📄 Use Filename** - Use the original filename as caption (extension removed).
7. **📝 Filename with Cap** - Combine cleaned filename + a custom caption you supply (filename on first line, your caption below).
8. **🔄 Add Text to Each** - Add text to each media (appends if caption exists, creates if empty).
9. **🖼️ Make Album** - Return media as Telegram album groups (batches of up to 10 items) using chosen caption logic.

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

- `/start` - Start the bot and see welcome message.
- `/help` - Show detailed help with all features.
- `/clear` - Clear pending media and start over.
- `/global_replacement <target> <replacement>` - Add or update a global replacement (applied automatically to every generated caption after mode processing). The replacement can contain spaces.
- `/list_global` - List all active global replacements for this chat.
- `/remove_replacement <index>` - Remove a global replacement by its 1-based index from `/list_global`.

### Global Replacements
Global replacements let you define substitutions that are applied to every caption before sending (after the selected mode's transformation). Useful for branding, tracking links, or mass corrections.

Example:
```
/global_replacement oldlink.com newlink.com/track
/global_replacement BRAND Awesome Channel ✅
/list_global
```
Then any caption containing `oldlink.com` will be replaced, and `BRAND` will become `Awesome Channel ✅` automatically.

Notes:
- Order of application follows the order you add them.
- Re-adding the same target updates its replacement (no duplicates kept).
- In-memory only; they reset if the bot restarts (you can extend with persistence later).

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

### Filename with Cap
- Choose "📝 Filename with Cap"
- Send your custom caption text when prompted
- Resulting caption: first line = cleaned filename, second line = your text

### Add Same Text to All
- Send multiple media (with or without captions)
- Choose "🔄 Add Text to Each"
- Type your text
- Appends to existing or creates new caption

## Notes

- Sends media back individually or in albums (when using Make Album).
- Original captions and filenames are preserved during collection.
- Link replace now uses a two-step target → replacement flow for precision.
- Global replacements applied after mode transformation; they affect final captions only.
- Voice messages cannot have captions (Telegram limitation).
- Per-chat state: multiple users can work concurrently without interference.
- Use `/clear` to cancel current batch and start fresh.
- Global replacements are ephemeral (lost on restart) unless persistence is added.

## Advanced Use Cases

**Scenario: Media with links that you want to replace**
1. Forward/send media from another source with promotional links
2. Choose "Replace Links" mode
3. Enter your affiliate/tracking link
4. All original links are replaced with yours

**Scenario: Want to add your branding to all media each time automatically**
1. Set a global replacement: `/global_replacement BRAND YourChannelName`
2. Use modes normally including captions containing `BRAND`
3. Every output swaps `BRAND` for `YourChannelName`
4. No need to manually append each batch

**Scenario: Make a clean album for sharing**
1. Send up to 25 media items
2. Wait for Done button and choose a caption mode
3. Tap "Make Album" button
4. Media returned in groups (10 max per Telegram album) with transformed captions

**Scenario: Clean up filenames for presentation**
1. Send documents with messy filenames
2. Choose "Use Filename" mode
3. Get clean captions from filenames (no extensions)

